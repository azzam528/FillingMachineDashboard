"""Pengujian endpoint baca: konfigurasi mesin, status telemetri, riwayat event, dan ringkasan."""

import pytest


@pytest.mark.asyncio
async def test_ambil_konfigurasi_mesin_sukses_dan_404(client):
    """GET /api/v1/mesin/{id} mengembalikan konfigurasi atau 404 jika tidak ada."""
    res1 = await client.get("/api/v1/mesin/mesin-01")
    assert res1.status_code == 200
    data = res1.json()
    assert data["_id"] == "mesin-01"
    assert data["jumlah_slot"] == 10
    assert "stasiun" in data

    res2 = await client.get("/api/v1/mesin/mesin-palsu-99")
    assert res2.status_code == 404


@pytest.mark.asyncio
async def test_ambil_status_terakhir_dan_filter_pengguna(client, auth_headers):
    """GET /api/v1/mesin/{id}/status mengembalikan telemetri terakhir (global dan per pengguna)."""
    # Saat belum ada telemetri -> 404
    res_empty = await client.get("/api/v1/mesin/mesin-01/status")
    assert res_empty.status_code == 404

    # Simpan telemetri 1 (Gibral pada 10:00:00)
    await client.post(
        "/api/v1/telemetri",
        headers=auth_headers,
        json=[
            {
                "waktu": "2026-10-29T10:00:00Z",
                "mesin_id": "mesin-01",
                "sesi_id": "gibral-1",
                "pengguna": "gibral",
                "darurat": False,
                "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
                "sudut_turret_deg": 36.0,
                "botol_selesai": 1,
                "isi_kotak": 1,
                "sisa_peti": 99,
                "gpio": {},
            }
        ],
    )

    # Simpan telemetri 2 (Haikal pada 10:01:00 - lebih baru)
    await client.post(
        "/api/v1/telemetri",
        headers=auth_headers,
        json=[
            {
                "waktu": "2026-10-29T10:01:00Z",
                "mesin_id": "mesin-01",
                "sesi_id": "haikal-1",
                "pengguna": "haikal",
                "darurat": True,
                "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
                "sudut_turret_deg": 72.0,
                "botol_selesai": 2,
                "isi_kotak": 2,
                "sisa_peti": 98,
                "gpio": {},
            }
        ],
    )

    # 1. Tanpa filter: harus mengembalikan data Haikal (terbaru)
    res_all = await client.get("/api/v1/mesin/mesin-01/status")
    assert res_all.status_code == 200
    assert res_all.json()["pengguna"] == "haikal"
    assert res_all.json()["darurat"] is True

    # 2. Filter pengguna=gibral: harus mengembalikan data Gibral
    res_gibral = await client.get("/api/v1/mesin/mesin-01/status?pengguna=gibral")
    assert res_gibral.status_code == 200
    assert res_gibral.json()["pengguna"] == "gibral"
    assert res_gibral.json()["darurat"] is False

    # 3. Filter pengguna yang belum kirim data -> 404
    res_naya = await client.get("/api/v1/mesin/mesin-01/status?pengguna=naya")
    assert res_naya.status_code == 404


@pytest.mark.asyncio
async def test_ambil_event_dan_filter(client, auth_headers):
    """GET /api/v1/mesin/{id}/event menguji sorting, filter jenis, pengguna, dan limit."""
    events = [
        {"waktu": "2026-10-29T10:00:00Z", "mesin_id": "mesin-01", "sesi_id": "s1", "pengguna": "gibral", "jenis": "START", "sumber": "pemain"},
        {"waktu": "2026-10-29T10:02:00Z", "mesin_id": "mesin-01", "sesi_id": "s1", "pengguna": "gibral", "jenis": "estop_tekan", "sumber": "pemain"},
        {"waktu": "2026-10-29T10:05:00Z", "mesin_id": "mesin-01", "sesi_id": "s2", "pengguna": "haikal", "jenis": "START", "sumber": "pemain"},
    ]
    for ev in events:
        await client.post("/api/v1/event", headers=auth_headers, json=ev)

    # 1. Ambil semua event: urut waktu desc (terbaru 10:05:00 duluan)
    res = await client.get("/api/v1/mesin/mesin-01/event")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 3
    assert data[0]["waktu"].startswith("2026-10-29T10:05:00")

    # 2. Filter jenis=START
    res_start = await client.get("/api/v1/mesin/mesin-01/event?jenis=START")
    assert res_start.status_code == 200
    assert len(res_start.json()) == 2

    # 3. Filter pengguna=gibral
    res_user = await client.get("/api/v1/mesin/mesin-01/event?pengguna=gibral")
    assert res_user.status_code == 200
    assert len(res_user.json()) == 2

    # 4. Limit valid dan invalid
    res_lim = await client.get("/api/v1/mesin/mesin-01/event?limit=1")
    assert res_lim.status_code == 200
    assert len(res_lim.json()) == 1

    res_lim_invalid = await client.get("/api/v1/mesin/mesin-01/event?limit=1001")
    assert res_lim_invalid.status_code == 400


@pytest.mark.asyncio
async def test_ringkasan_produksi_hitungan_manual(client, auth_headers):
    """GET /api/v1/mesin/{id}/ringkasan diverifikasi dengan hitungan manual persis."""
    # Skenario Data Botol:
    # 1. Gibral: 10:00:00 -> 10:00:10 (siklus 10 detik, OK)
    # 2. Gibral: 10:01:00 -> 10:01:20 (siklus 20 detik, TIDAK_PENUH / gagal)
    # 3. Haikal: 10:05:00 -> 10:05:30 (siklus 30 detik, OK)
    botol_data = [
        {
            "mesin_id": "mesin-01",
            "sesi_id": "gibral-sesi",
            "pengguna": "gibral",
            "nomor": 1,
            "slot": 1,
            "waktu_masuk": "2026-10-29T10:00:00Z",
            "waktu_keluar": "2026-10-29T10:00:10Z",
            "level_isi": 1.0,
            "bertutup": True,
            "status": "OK",
        },
        {
            "mesin_id": "mesin-01",
            "sesi_id": "gibral-sesi",
            "pengguna": "gibral",
            "nomor": 2,
            "slot": 2,
            "waktu_masuk": "2026-10-29T10:01:00Z",
            "waktu_keluar": "2026-10-29T10:01:20Z",
            "level_isi": 0.5,
            "bertutup": True,
            "status": "TIDAK_PENUH",
        },
        {
            "mesin_id": "mesin-01",
            "sesi_id": "haikal-sesi",
            "pengguna": "haikal",
            "nomor": 1,
            "slot": 3,
            "waktu_masuk": "2026-10-29T10:05:00Z",
            "waktu_keluar": "2026-10-29T10:05:30Z",
            "level_isi": 1.0,
            "bertutup": True,
            "status": "OK",
        },
    ]
    for b in botol_data:
        res = await client.post("/api/v1/botol", headers=auth_headers, json=b)
        assert res.status_code == 201

    # Skenario Event E-stop:
    # Gibral: tekan 10:02:00 -> lepas 10:02:40 (40 detik)
    # Haikal: tekan 10:06:00 -> lepas 10:06:20 (20 detik)
    event_data = [
        {"waktu": "2026-10-29T10:02:00Z", "mesin_id": "mesin-01", "sesi_id": "gibral-sesi", "pengguna": "gibral", "jenis": "estop_tekan", "sumber": "pemain"},
        {"waktu": "2026-10-29T10:02:40Z", "mesin_id": "mesin-01", "sesi_id": "gibral-sesi", "pengguna": "gibral", "jenis": "estop_lepas", "sumber": "pemain"},
        {"waktu": "2026-10-29T10:06:00Z", "mesin_id": "mesin-01", "sesi_id": "haikal-sesi", "pengguna": "haikal", "jenis": "estop_tekan", "sumber": "pemain"},
        {"waktu": "2026-10-29T10:06:20Z", "mesin_id": "mesin-01", "sesi_id": "haikal-sesi", "pengguna": "haikal", "jenis": "estop_lepas", "sumber": "pemain"},
    ]
    for ev in event_data:
        res = await client.post("/api/v1/event", headers=auth_headers, json=ev)
        assert res.status_code == 201

    # =========================================================================
    # 1. Ringkasan Keseluruhan (tanpa filter pengguna)
    # =========================================================================
    res_all = await client.get("/api/v1/mesin/mesin-01/ringkasan")
    assert res_all.status_code == 200
    d_all = res_all.json()
    assert d_all["jumlah_botol"] == 3
    assert d_all["botol_gagal"] == 1
    # Rata-rata siklus = (10 + 20 + 30) / 3 = 20.0 detik
    assert d_all["rata_rata_waktu_siklus_detik"] == 20.0
    # Total durasi darurat = 40 + 20 = 60.0 detik
    assert d_all["total_durasi_darurat_detik"] == 60.0

    # Verifikasi rincian per pengguna
    assert "rincian_pengguna" in d_all
    rincian = d_all["rincian_pengguna"]
    assert "gibral" in rincian
    assert rincian["gibral"]["jumlah_botol"] == 2
    assert rincian["gibral"]["botol_gagal"] == 1
    assert rincian["gibral"]["rata_rata_waktu_siklus_detik"] == 15.0
    assert rincian["gibral"]["total_durasi_darurat_detik"] == 40.0

    assert "haikal" in rincian
    assert rincian["haikal"]["jumlah_botol"] == 1
    assert rincian["haikal"]["botol_gagal"] == 0
    assert rincian["haikal"]["rata_rata_waktu_siklus_detik"] == 30.0
    assert rincian["haikal"]["total_durasi_darurat_detik"] == 20.0

    # =========================================================================
    # 2. Ringkasan dengan filter pengguna=gibral
    # =========================================================================
    res_gibral = await client.get("/api/v1/mesin/mesin-01/ringkasan?pengguna=gibral")
    assert res_gibral.status_code == 200
    d_gibral = res_gibral.json()
    assert d_gibral["pengguna"] == "gibral"
    assert d_gibral["jumlah_botol"] == 2
    assert d_gibral["botol_gagal"] == 1
    assert d_gibral["rata_rata_waktu_siklus_detik"] == 15.0
    assert d_gibral["total_durasi_darurat_detik"] == 40.0

    # =========================================================================
    # 3. Ringkasan dengan filter rentang waktu
    # =========================================================================
    res_range = await client.get(
        "/api/v1/mesin/mesin-01/ringkasan?dari=2026-10-29T10:00:00Z&sampai=2026-10-29T10:03:00Z"
    )
    assert res_range.status_code == 200
    d_range = res_range.json()
    # Hanya botol 1 dan 2 yang keluar sebelum 10:03:00
    assert d_range["jumlah_botol"] == 2
    assert d_range["botol_gagal"] == 1
    assert d_range["rata_rata_waktu_siklus_detik"] == 15.0
    # Hanya E-stop Gibral (40s) yang terjadi dalam rentang ini
    assert d_range["total_durasi_darurat_detik"] == 40.0

    # =========================================================================
    # 4. Filter 'dari' > 'sampai' harus ditolak 400
    # =========================================================================
    res_bad = await client.get(
        "/api/v1/mesin/mesin-01/ringkasan?dari=2026-10-29T10:05:00Z&sampai=2026-10-29T10:01:00Z"
    )
    assert res_bad.status_code == 400


@pytest.mark.asyncio
async def test_durasi_estop_aktif_tanpa_lepas(client, auth_headers):
    """Jika E-stop ditekan dan belum dilepas, durasi dihitung sampai 'sampai'."""
    ev = {
        "waktu": "2026-10-29T11:00:00Z",
        "mesin_id": "mesin-01",
        "sesi_id": "alvin-sesi",
        "pengguna": "alvin",
        "jenis": "estop_tekan",
        "sumber": "pemain",
    }
    await client.post("/api/v1/event", headers=auth_headers, json=ev)

    # Query dengan sampai 11:00:45Z -> durasi darurat harus 45 detik
    res = await client.get(
        "/api/v1/mesin/mesin-01/ringkasan?sesi_id=alvin-sesi&dari=2026-10-29T11:00:00Z&sampai=2026-10-29T11:00:45Z"
    )
    assert res.status_code == 200
    assert res.json()["total_durasi_darurat_detik"] == 45.0

