"""Integration test lengkap untuk alur Unity Digital Twin -> FastAPI -> MongoDB
dan Frontend MES -> FastAPI -> MongoDB (Tahap 5 Finalisasi).

Menguji:
1. Alur Ingest Unity:
   - Pengiriman telemetri batch (1-10 item), timestamp UTC, validasi mesin_id, dedup id_kirim.
   - Pengiriman event mesin (START, STOP, estop_tekan, estop_lepas), idempotency DuplicateKeyError.
   - Pengiriman data botol (inspeksi, level_isi, bertutup, status OK/TIDAK_PENUH/TANPA_TUTUP).
   - Pengujian keamanan API Key (X-Api-Key) dan penolakan payload tidak valid.

2. Alur Baca Frontend MES:
   - Pemeriksaan CORS preflight dan request dari origin frontend yang sah.
   - Live Monitoring: konfigurasi mesin, telemetri status terakhir, dan riwayat event realtime.
   - Produksi & Kualitas: ringkasan agregat, filter sesi/pengguna, metrik kegagalan defect.
   - Traceability: pencarian riwayat botol, filter status/slot, detail botol spesifik beserta durasi siklus.
   - Downtime & Laporan: perhitungan durasi darurat E-stop berpasangan, insiden downtime, dan laporan terpadu.

3. Alur End-to-End Siklus Lengkap:
   - Simulasi alur kerja pabrik penuh dari start mesin, rotasi telemetri, insiden e-stop,
     inspeksi botol, hingga pelaporan di frontend MES melalui prefix /api maupun /api/v1.
"""

from datetime import datetime, timezone
import pytest


@pytest.mark.asyncio
async def test_unity_telemetry_ingestion_and_deduplication(client, auth_headers):
    """Menguji alur Unity mengirim batch telemetri ke FastAPI -> MongoDB:
    - Batch valid 1-10 data tersimpan.
    - Idempotensi: id_kirim yang sama diabaikan tanpa error (duplikat_diabaikan).
    - Validasi: batas batch > 10 dan batch kosong ditolak (400).
    - Validasi: mesin_id tidak terdaftar ditolak (400).
    - Keamanan: tanpa API Key ditolak (401).
    """
    # 1. Tanpa API Key -> 401
    unauth_res = await client.post(
        "/api/v1/telemetri",
        json=[
            {
                "waktu": "2026-10-30T08:00:00Z",
                "mesin_id": "mesin-01",
                "sesi_id": "unity-sesi-1",
                "pengguna": "gibral",
                "darurat": False,
                "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
                "sudut_turret_deg": 0.0,
                "botol_selesai": 0,
                "isi_kotak": 0,
                "sisa_peti": 12,
                "gpio": {},
            }
        ],
    )
    assert unauth_res.status_code == 401

    # 2. Kirim batch valid (3 dokumen) dengan id_kirim unik via /api/v1/telemetri
    tele_batch = [
        {
            "waktu": "2026-10-30T08:00:00Z",
            "mesin_id": "mesin-01",
            "sesi_id": "unity-sesi-1",
            "pengguna": "gibral",
            "id_kirim": "telem-u-01",
            "darurat": False,
            "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
            "sudut_turret_deg": 0.0,
            "mode": "Berjalan",
            "tahap": "Pengisian",
            "langkah": 1,
            "botol_selesai": 0,
            "isi_kotak": 0,
            "sisa_peti": 12,
            "gpio": {"step": True, "dir": False, "pompa": False},
        },
        {
            "waktu": "2026-10-30T08:00:01Z",
            "mesin_id": "mesin-01",
            "sesi_id": "unity-sesi-1",
            "pengguna": "gibral",
            "id_kirim": "telem-u-02",
            "darurat": False,
            "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
            "sudut_turret_deg": 36.0,
            "mode": "Berjalan",
            "tahap": "Pengisian",
            "langkah": 2,
            "botol_selesai": 0,
            "isi_kotak": 0,
            "sisa_peti": 12,
            "gpio": {"step": False, "dir": False, "pompa": True},
        },
        {
            "waktu": "2026-10-30T08:00:02Z",
            "mesin_id": "mesin-01",
            "sesi_id": "unity-sesi-1",
            "pengguna": "gibral",
            "id_kirim": "telem-u-03",
            "darurat": False,
            "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
            "sudut_turret_deg": 72.0,
            "mode": "Berjalan",
            "tahap": "Capping",
            "langkah": 3,
            "botol_selesai": 1,
            "isi_kotak": 1,
            "sisa_peti": 12,
            "gpio": {"step": True, "dir": False, "pompa": False},
        },
    ]

    res_batch = await client.post("/api/v1/telemetri", headers=auth_headers, json=tele_batch)
    assert res_batch.status_code == 201
    data_batch = res_batch.json()
    assert data_batch["status"] == "sukses"
    assert data_batch["tersimpan"] == 3
    assert data_batch["duplikat_diabaikan"] == 0

    # 3. Kirim ulang batch yang sama persis (simulasi retry Unity akibat latency jaringan)
    res_retry = await client.post("/api/v1/telemetri", headers=auth_headers, json=tele_batch)
    assert res_retry.status_code == 201
    data_retry = res_retry.json()
    assert data_retry["tersimpan"] == 0
    assert data_retry["duplikat_diabaikan"] == 3

    # 4. Akses melalui prefix /api/telemetri juga berfungsi setara
    new_item = [
        {
            "waktu": "2026-10-30T08:00:03Z",
            "mesin_id": "mesin-01",
            "sesi_id": "unity-sesi-1",
            "pengguna": "gibral",
            "id_kirim": "telem-u-04",
            "darurat": False,
            "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
            "sudut_turret_deg": 108.0,
            "botol_selesai": 1,
            "isi_kotak": 1,
            "sisa_peti": 12,
            "gpio": {},
        }
    ]
    res_api_prefix = await client.post("/api/telemetri", headers=auth_headers, json=new_item)
    assert res_api_prefix.status_code == 201
    assert res_api_prefix.json()["tersimpan"] == 1

    # 5. Uji batas batch: lebih dari 10 ditolak (400 Bad Request)
    overload_items = [
        {
            "waktu": f"2026-10-30T08:01:{i:02d}Z",
            "mesin_id": "mesin-01",
            "sesi_id": "u-overflow",
            "pengguna": "gibral",
            "darurat": False,
            "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
            "sudut_turret_deg": float(i * 10),
            "botol_selesai": i,
            "isi_kotak": i,
            "sisa_peti": 10,
            "gpio": {},
        }
        for i in range(11)
    ]
    res_overload = await client.post("/api/v1/telemetri", headers=auth_headers, json=overload_items)
    assert res_overload.status_code == 400

    # 6. Uji batch kosong -> 400
    res_empty = await client.post("/api/v1/telemetri", headers=auth_headers, json=[])
    assert res_empty.status_code == 400

    # 7. Uji mesin_id tidak terdaftar -> 400
    invalid_machine = [
        {
            "waktu": "2026-10-30T08:02:00Z",
            "mesin_id": "mesin-gaib-99",
            "sesi_id": "u-invalid",
            "pengguna": "gibral",
            "darurat": False,
            "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
            "sudut_turret_deg": 0.0,
            "botol_selesai": 0,
            "isi_kotak": 0,
            "sisa_peti": 12,
            "gpio": {},
        }
    ]
    res_inv_mach = await client.post("/api/v1/telemetri", headers=auth_headers, json=invalid_machine)
    assert res_inv_mach.status_code == 400
    assert "tidak terdaftar" in res_inv_mach.json()["detail"]


@pytest.mark.asyncio
async def test_unity_event_and_bottle_ingestion_idempotency(client, auth_headers):
    """Menguji alur Unity mengirim event mesin dan botol selesai ke FastAPI -> MongoDB:
    - Event mesin: START, estop_tekan, estop_lepas.
    - Idempotensi event berdasarkan id_kirim unik.
    - Botol selesai: data inspeksi, level_isi, bertutup, status kualitas.
    - Idempotensi botol berdasarkan id_kirim unik.
    """
    # 1. Kirim event START
    ev_start = {
        "waktu": "2026-10-30T08:00:00Z",
        "mesin_id": "mesin-01",
        "sesi_id": "sesi-e2e-01",
        "pengguna": "haikal",
        "jenis": "START",
        "sumber": "pemain",
        "id_kirim": "ev-u-start-01",
        "pesan": "Mesin dijalankan oleh operator Haikal",
    }
    res_ev = await client.post("/api/v1/event", headers=auth_headers, json=ev_start)
    assert res_ev.status_code == 201
    assert res_ev.json()["tersimpan"] is True
    assert res_ev.json()["id_kirim"] == "ev-u-start-01"

    # Kirim ulang event yang sama -> respons idempotent (tersimpan: False, pesan: duplikat diabaikan)
    res_ev_dup = await client.post("/api/v1/event", headers=auth_headers, json=ev_start)
    assert res_ev_dup.status_code == 201
    assert res_ev_dup.json()["tersimpan"] is False
    assert res_ev_dup.json()["pesan"] == "duplikat diabaikan"

    # 2. Kirim botol selesai (1 OK, 1 TIDAK_PENUH)
    botol_ok = {
        "mesin_id": "mesin-01",
        "sesi_id": "sesi-e2e-01",
        "pengguna": "haikal",
        "id_kirim": "btl-u-01",
        "nomor": 1,
        "slot": 1,
        "waktu_masuk": "2026-10-30T08:00:05Z",
        "waktu_isi_mulai": "2026-10-30T08:00:08Z",
        "waktu_isi_selesai": "2026-10-30T08:00:12Z",
        "waktu_tutup": "2026-10-30T08:00:14Z",
        "waktu_keluar": "2026-10-30T08:00:16Z",
        "level_isi": 1.0,
        "bertutup": True,
        "status": "OK",
    }
    res_b1 = await client.post("/api/v1/botol", headers=auth_headers, json=botol_ok)
    assert res_b1.status_code == 201
    assert res_b1.json()["tersimpan"] is True

    # Kirim ulang botol yang sama -> idempotent
    res_b1_dup = await client.post("/api/v1/botol", headers=auth_headers, json=botol_ok)
    assert res_b1_dup.status_code == 201
    assert res_b1_dup.json()["tersimpan"] is False
    assert res_b1_dup.json()["pesan"] == "duplikat diabaikan"

    # Kirim botol gagal (TIDAK_PENUH)
    botol_defect = {
        "mesin_id": "mesin-01",
        "sesi_id": "sesi-e2e-01",
        "pengguna": "haikal",
        "id_kirim": "btl-u-02",
        "nomor": 2,
        "slot": 2,
        "waktu_masuk": "2026-10-30T08:00:16Z",
        "waktu_isi_mulai": "2026-10-30T08:00:18Z",
        "waktu_isi_selesai": "2026-10-30T08:00:20Z",
        "waktu_tutup": "2026-10-30T08:00:22Z",
        "waktu_keluar": "2026-10-30T08:00:24Z",
        "level_isi": 0.45,
        "bertutup": True,
        "status": "TIDAK_PENUH",
    }
    res_b2 = await client.post("/api/botol", headers=auth_headers, json=botol_defect)
    assert res_b2.status_code == 201
    assert res_b2.json()["tersimpan"] is True


@pytest.mark.asyncio
async def test_frontend_mes_monitoring_and_analytics_flow(client, auth_headers):
    """Menguji alur Frontend MES mengakses seluruh endpoint monitoring & analitik:
    - Preflight CORS & Request dengan Origin Frontend yang diizinkan.
    - Live Monitoring: Konfigurasi Mesin, Status Real-Time, Riwayat Event.
    - Produksi & Kualitas: Ringkasan Produksi, Kategori Defect.
    - Traceability: List Botol, Filter Status, Detail Botol dengan Durasi Siklus.
    - Downtime: E-stop durasi dan kejadian.
    - Laporan: Laporan Terpadu (Produksi + Kualitas + Downtime).
    """
    origin = "http://localhost:3000"

    # 1. CORS Preflight OPTIONS
    preflight = await client.options(
        "/api/mesin/mesin-01/status",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Api-Key,Content-Type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == origin

    # 2. Seed data operasional mesin untuk pengujian alur Frontend MES
    # Telemetri live
    await client.post(
        "/api/v1/telemetri",
        headers=auth_headers,
        json=[
            {
                "waktu": "2026-10-30T09:00:00Z",
                "mesin_id": "mesin-01",
                "sesi_id": "sesi-frontend-01",
                "pengguna": "alvin",
                "darurat": False,
                "mode": "Berjalan",
                "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
                "sudut_turret_deg": 144.0,
                "botol_selesai": 5,
                "isi_kotak": 5,
                "sisa_peti": 11,
                "tahap": "Pengisian",
                "langkah": 2,
                "gpio": {"step": True, "pompa": True},
            }
        ],
    )

    # Event darurat E-stop berpasangan (ditekan 09:02:00, dilepas 09:02:30 -> downtime 30s)
    events = [
        {
            "waktu": "2026-10-30T09:02:00Z",
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-frontend-01",
            "pengguna": "alvin",
            "jenis": "estop_tekan",
            "sumber": "operator",
            "pesan": "Emergency button pressed due to bottle jam",
        },
        {
            "waktu": "2026-10-30T09:02:30Z",
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-frontend-01",
            "pengguna": "alvin",
            "jenis": "estop_lepas",
            "sumber": "operator",
            "pesan": "Jam cleared, emergency button released",
        },
    ]
    for ev in events:
        await client.post("/api/v1/event", headers=auth_headers, json=ev)

    # Botol: 2 OK, 1 TIDAK_PENUH, 1 TANPA_TUTUP
    botol_items = [
        {
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-frontend-01",
            "pengguna": "alvin",
            "nomor": 1,
            "slot": 1,
            "waktu_masuk": "2026-10-30T09:00:10Z",
            "waktu_keluar": "2026-10-30T09:00:20Z",
            "level_isi": 1.0,
            "bertutup": True,
            "status": "OK",
        },
        {
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-frontend-01",
            "pengguna": "alvin",
            "nomor": 2,
            "slot": 2,
            "waktu_masuk": "2026-10-30T09:00:20Z",
            "waktu_keluar": "2026-10-30T09:00:40Z",
            "level_isi": 0.5,
            "bertutup": True,
            "status": "TIDAK_PENUH",
        },
        {
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-frontend-01",
            "pengguna": "alvin",
            "nomor": 3,
            "slot": 3,
            "waktu_masuk": "2026-10-30T09:00:40Z",
            "waktu_keluar": "2026-10-30T09:00:55Z",
            "level_isi": 1.0,
            "bertutup": False,
            "status": "TANPA_TUTUP",
        },
        {
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-frontend-01",
            "pengguna": "alvin",
            "nomor": 4,
            "slot": 4,
            "waktu_masuk": "2026-10-30T09:01:00Z",
            "waktu_keluar": "2026-10-30T09:01:15Z",
            "level_isi": 1.0,
            "bertutup": True,
            "status": "OK",
        },
    ]
    for b in botol_items:
        await client.post("/api/v1/botol", headers=auth_headers, json=b)

    # =========================================================================
    # A. Verifikasi Halaman Live Monitoring Frontend MES
    # =========================================================================
    # 1. Konfigurasi Mesin: GET /api/mesin/mesin-01
    res_cfg = await client.get("/api/mesin/mesin-01", headers={"Origin": origin})
    assert res_cfg.status_code == 200
    cfg = res_cfg.json()
    assert cfg["_id"] == "mesin-01"
    assert cfg["jumlah_slot"] == 10
    assert cfg["sudut_per_slot_deg"] == 36
    assert "stasiun" in cfg
    assert "pin_gpio" in cfg

    # 2. Status Mesin Terkini: GET /api/mesin/mesin-01/status
    res_status = await client.get("/api/mesin/mesin-01/status", headers={"Origin": origin})
    assert res_status.status_code == 200
    st = res_status.json()
    assert st["mesin_id"] == "mesin-01"
    assert st["mode"] == "Berjalan"
    assert st["mcb"]["utama"] is True
    assert st["sudut_turret_deg"] == 144.0
    assert st["botol_selesai"] == 5
    assert st["tahap"] == "Pengisian"
    assert st["langkah"] == 2
    assert st["gpio"]["pompa"] is True

    # 3. Riwayat Event Live: GET /api/mesin/mesin-01/event
    res_ev_live = await client.get("/api/mesin/mesin-01/event?limit=10", headers={"Origin": origin})
    assert res_ev_live.status_code == 200
    events_live = res_ev_live.json()
    assert len(events_live) == 2
    assert events_live[0]["jenis"] == "estop_lepas"
    assert events_live[1]["jenis"] == "estop_tekan"
    assert res_ev_live.headers.get("X-Total-Count") == "2"

    # =========================================================================
    # B. Verifikasi Halaman Produksi & Kualitas Frontend MES
    # =========================================================================
    # GET /api/mesin/mesin-01/ringkasan
    res_ringkasan = await client.get("/api/mesin/mesin-01/ringkasan", headers={"Origin": origin})
    assert res_ringkasan.status_code == 200
    rg = res_ringkasan.json()
    assert rg["jumlah_botol"] == 4
    assert rg["botol_ok"] == 2
    assert rg["botol_gagal"] == 2
    assert rg["kategori_kegagalan"]["TIDAK_PENUH"] == 1
    assert rg["kategori_kegagalan"]["TANPA_TUTUP"] == 1
    # Rata-rata siklus = (10 + 20 + 15 + 15) / 4 = 60 / 4 = 15.0 detik
    assert rg["rata_rata_waktu_siklus_detik"] == 15.0
    assert rg["total_durasi_darurat_detik"] == 30.0
    assert rg["rincian_pengguna"]["alvin"]["jumlah_botol"] == 4

    # =========================================================================
    # C. Verifikasi Halaman Traceability Frontend MES
    # =========================================================================
    # 1. Daftar Botol dengan Pagination: GET /api/mesin/mesin-01/botol
    res_botol = await client.get("/api/mesin/mesin-01/botol?wrap=true&limit=2&page=1", headers={"Origin": origin})
    assert res_botol.status_code == 200
    b_data = res_botol.json()
    assert b_data["total"] == 4
    assert b_data["page"] == 1
    assert b_data["limit"] == 2
    assert len(b_data["items"]) == 2

    # 2. Filter status defect: status=TANPA_TUTUP
    res_filter_status = await client.get("/api/mesin/mesin-01/botol?status=TANPA_TUTUP", headers={"Origin": origin})
    assert res_filter_status.status_code == 200
    defect_list = res_filter_status.json()
    assert len(defect_list) == 1
    assert defect_list[0]["nomor"] == 3
    assert defect_list[0]["bertutup"] is False

    # 3. Detail Botol Spesifik: GET /api/mesin/mesin-01/botol/2
    res_b2 = await client.get("/api/mesin/mesin-01/botol/2", headers={"Origin": origin})
    assert res_b2.status_code == 200
    b2_doc = res_b2.json()
    assert b2_doc["nomor"] == 2
    assert b2_doc["status"] == "TIDAK_PENUH"
    assert b2_doc["slot"] == 2
    # Durasi siklus = 09:00:40 - 09:00:20 = 20.0 detik
    assert b2_doc["durasi_siklus_detik"] == 20.0

    # 4. Detail Botol tidak ada -> 404
    res_b99 = await client.get("/api/mesin/mesin-01/botol/99", headers={"Origin": origin})
    assert res_b99.status_code == 404

    # =========================================================================
    # D. Verifikasi Halaman Downtime Frontend MES
    # =========================================================================
    # GET /api/mesin/mesin-01/downtime
    res_down = await client.get("/api/mesin/mesin-01/downtime", headers={"Origin": origin})
    assert res_down.status_code == 200
    dt_data = res_down.json()
    assert dt_data["total_durasi_downtime_detik"] == 30.0
    assert dt_data["jumlah_kejadian_downtime"] == 1
    assert len(dt_data["kejadian"]) == 1
    incident = dt_data["kejadian"][0]
    assert incident["status"] == "SELESAI"
    assert incident["durasi_detik"] == 30.0
    assert "bottle jam" in incident["pesan"]

    # =========================================================================
    # E. Verifikasi Halaman Laporan Terpadu Frontend MES
    # =========================================================================
    # GET /api/mesin/mesin-01/laporan
    res_lap = await client.get("/api/mesin/mesin-01/laporan", headers={"Origin": origin})
    assert res_lap.status_code == 200
    lap = res_lap.json()
    assert lap["mesin_id"] == "mesin-01"
    # Seksion Produksi
    assert lap["produksi"]["total_botol"] == 4
    assert lap["produksi"]["rata_rata_waktu_siklus_detik"] == 15.0
    # Seksion Kualitas
    assert lap["kualitas"]["botol_ok"] == 2
    assert lap["kualitas"]["botol_gagal"] == 2
    assert lap["kualitas"]["persentase_ok"] == 50.0
    assert lap["kualitas"]["kategori_kegagalan"]["TIDAK_PENUH"] == 1
    assert lap["kualitas"]["kategori_kegagalan"]["TANPA_TUTUP"] == 1
    # Seksion Downtime
    assert lap["downtime"]["total_durasi_detik"] == 30.0
    assert lap["downtime"]["jumlah_kejadian"] == 1


@pytest.mark.asyncio
async def test_end_to_end_full_production_cycle_simulation(client, auth_headers):
    """Simulasi End-to-End Siklus Produksi Nyata Pabrik:
    1. Unity menyalakan mesin (Kirim event START).
    2. Unity memutar turret dan mengisi botol (Kirim telemetri batch step & GPIO).
    3. Terjadi kendala darurat: E-Stop ditekan (Kirim event estop_tekan dan telemetri darurat=True).
    4. Operator memperbaiki kendala, E-Stop dilepas (Kirim event estop_lepas).
    5. Botol selesai dikeluarkan: 1 botol lolos inspeksi (OK), 1 botol cacat (TIDAK_PENUH).
    6. Frontend MES memantau live status: mesin kembali mode Berjalan, darurat=False.
    7. Frontend MES membaca laporan dan ringkasan: data produksi, kualitas, dan downtime tercatat akurat.
    8. Seluruh endpoint dipastikan identik baik diakses melalui prefix /api maupun /api/v1.
    """
    sesi = "simulasi-pabrik-2026"
    operator = "naya"

    # Step 1: Mesin START
    ev_start = {
        "waktu": "2026-10-30T10:00:00Z",
        "mesin_id": "mesin-01",
        "sesi_id": sesi,
        "pengguna": operator,
        "jenis": "START",
        "sumber": "operator",
        "pesan": "Shift pagi dimulai oleh Naya",
    }
    r = await client.post("/api/v1/event", headers=auth_headers, json=ev_start)
    assert r.status_code == 201

    # Step 2: Telemetri operasional berjalan
    tele_normal = [
        {
            "waktu": "2026-10-30T10:00:05Z",
            "mesin_id": "mesin-01",
            "sesi_id": sesi,
            "pengguna": operator,
            "darurat": False,
            "mode": "Berjalan",
            "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
            "sudut_turret_deg": 36.0,
            "botol_selesai": 0,
            "isi_kotak": 0,
            "sisa_peti": 12,
            "tahap": "Infeed",
            "langkah": 1,
            "gpio": {},
        },
        {
            "waktu": "2026-10-30T10:00:10Z",
            "mesin_id": "mesin-01",
            "sesi_id": sesi,
            "pengguna": operator,
            "darurat": False,
            "mode": "Berjalan",
            "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
            "sudut_turret_deg": 180.0,
            "botol_selesai": 0,
            "isi_kotak": 0,
            "sisa_peti": 12,
            "tahap": "Pengisian",
            "langkah": 2,
            "gpio": {"pompa": True},
        },
    ]
    r = await client.post("/api/v1/telemetri", headers=auth_headers, json=tele_normal)
    assert r.status_code == 201

    # Step 3: E-Stop ditekan (10:00:15)
    ev_estop_on = {
        "waktu": "2026-10-30T10:00:15Z",
        "mesin_id": "mesin-01",
        "sesi_id": sesi,
        "pengguna": operator,
        "jenis": "estop_tekan",
        "sumber": "pemain",
        "pesan": "Emergency stop ditekan!",
    }
    r = await client.post("/api/v1/event", headers=auth_headers, json=ev_estop_on)
    assert r.status_code == 201

    tele_darurat = [
        {
            "waktu": "2026-10-30T10:00:16Z",
            "mesin_id": "mesin-01",
            "sesi_id": sesi,
            "pengguna": operator,
            "darurat": True,
            "mode": "Darurat",
            "mcb": {"utama": True, "mesin": False, "kontrol": True, "lampu": True},
            "sudut_turret_deg": 180.0,
            "botol_selesai": 0,
            "isi_kotak": 0,
            "sisa_peti": 12,
            "gpio": {},
        }
    ]
    r = await client.post("/api/v1/telemetri", headers=auth_headers, json=tele_darurat)
    assert r.status_code == 201

    # Frontend MES Live Check saat darurat:
    status_darurat = await client.get("/api/mesin/mesin-01/status")
    assert status_darurat.status_code == 200
    assert status_darurat.json()["darurat"] is True
    assert status_darurat.json()["mode"] == "Darurat"

    # Step 4: E-Stop dilepas setelah 20 detik (10:00:35)
    ev_estop_off = {
        "waktu": "2026-10-30T10:00:35Z",
        "mesin_id": "mesin-01",
        "sesi_id": sesi,
        "pengguna": operator,
        "jenis": "estop_lepas",
        "sumber": "pemain",
        "pesan": "Emergency stop dilepas, siap melanjutkan",
    }
    r = await client.post("/api/v1/event", headers=auth_headers, json=ev_estop_off)
    assert r.status_code == 201

    # Step 5: Mesin kembali normal dan menyelesaikan 2 botol
    tele_recovery = [
        {
            "waktu": "2026-10-30T10:00:40Z",
            "mesin_id": "mesin-01",
            "sesi_id": sesi,
            "pengguna": operator,
            "darurat": False,
            "mode": "Berjalan",
            "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
            "sudut_turret_deg": 216.0,
            "botol_selesai": 1,
            "isi_kotak": 1,
            "sisa_peti": 12,
            "gpio": {},
        },
        {
            "waktu": "2026-10-30T10:01:00Z",
            "mesin_id": "mesin-01",
            "sesi_id": sesi,
            "pengguna": operator,
            "darurat": False,
            "mode": "Berjalan",
            "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
            "sudut_turret_deg": 252.0,
            "botol_selesai": 2,
            "isi_kotak": 2,
            "sisa_peti": 12,
            "gpio": {},
        },
    ]
    r = await client.post("/api/v1/telemetri", headers=auth_headers, json=tele_recovery)
    assert r.status_code == 201

    # Botol 1: OK
    b1 = {
        "mesin_id": "mesin-01",
        "sesi_id": sesi,
        "pengguna": operator,
        "nomor": 1,
        "slot": 1,
        "waktu_masuk": "2026-10-30T10:00:05Z",
        "waktu_keluar": "2026-10-30T10:00:40Z",
        "level_isi": 1.0,
        "bertutup": True,
        "status": "OK",
    }
    # Botol 2: TIDAK_PENUH (terganggu saat E-Stop)
    b2 = {
        "mesin_id": "mesin-01",
        "sesi_id": sesi,
        "pengguna": operator,
        "nomor": 2,
        "slot": 2,
        "waktu_masuk": "2026-10-30T10:00:10Z",
        "waktu_keluar": "2026-10-30T10:01:00Z",
        "level_isi": 0.35,
        "bertutup": True,
        "status": "TIDAK_PENUH",
    }
    await client.post("/api/v1/botol", headers=auth_headers, json=b1)
    await client.post("/api/v1/botol", headers=auth_headers, json=b2)

    # Step 6: Frontend MES memverifikasi pemulihan status
    st_recovered = await client.get("/api/mesin/mesin-01/status")
    assert st_recovered.status_code == 200
    assert st_recovered.json()["darurat"] is False
    assert st_recovered.json()["mode"] == "Berjalan"
    assert st_recovered.json()["botol_selesai"] == 2

    # Step 7: Verifikasi Laporan Terpadu via prefix /api
    lap_res = await client.get(f"/api/mesin/mesin-01/laporan?sesi_id={sesi}")
    assert lap_res.status_code == 200
    lap = lap_res.json()
    assert lap["produksi"]["total_botol"] == 2
    assert lap["kualitas"]["botol_ok"] == 1
    assert lap["kualitas"]["botol_gagal"] == 1
    assert lap["kualitas"]["persentase_ok"] == 50.0
    assert lap["kualitas"]["kategori_kegagalan"]["TIDAK_PENUH"] == 1
    assert lap["downtime"]["total_durasi_detik"] == 20.0
    assert lap["downtime"]["jumlah_kejadian"] == 1

    # Step 8: Verifikasi konsistensi akses via /api/v1 dan /api
    lap_v1_res = await client.get(f"/api/v1/mesin/mesin-01/laporan?sesi_id={sesi}")
    assert lap_v1_res.status_code == 200
    assert lap_v1_res.json() == lap
