"""Pengujian endpoint Produksi, Kualitas, Downtime, Traceability, dan Laporan (Tahap 4 MES):
- GET /api/mesin/{id}/ringkasan (Produksi & Kualitas)
- GET /api/mesin/{id}/botol (Traceability & Riwayat Kualitas)
- GET /api/mesin/{id}/botol/{nomor} (Traceability 1 Botol)
- GET /api/mesin/{id}/downtime (Downtime E-Stop)
- GET /api/mesin/{id}/laporan (Laporan Terpadu)
"""

import pytest


@pytest.fixture
async def seed_mes_data(client, auth_headers):
    """Seed data botol dan event darurat untuk pengujian analitik MES."""
    # 1. Tiga data botol dengan berbagai status kualitas:
    # Botol 1: OK, slot 1, siklus 10 detik
    # Botol 2: TIDAK_PENUH, slot 2, siklus 20 detik
    # Botol 3: TANPA_TUTUP, slot 3, siklus 15 detik
    botol_list = [
        {
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-prod-01",
            "pengguna": "gibral",
            "id_kirim": "btl-t4-01",
            "nomor": 1,
            "slot": 1,
            "waktu_masuk": "2026-10-29T10:00:00Z",
            "waktu_isi_mulai": "2026-10-29T10:00:02Z",
            "waktu_isi_selesai": "2026-10-29T10:00:06Z",
            "waktu_tutup": "2026-10-29T10:00:08Z",
            "waktu_keluar": "2026-10-29T10:00:10Z",
            "level_isi": 1.0,
            "bertutup": True,
            "status": "OK",
        },
        {
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-prod-01",
            "pengguna": "gibral",
            "id_kirim": "btl-t4-02",
            "nomor": 2,
            "slot": 2,
            "waktu_masuk": "2026-10-29T10:00:10Z",
            "waktu_isi_mulai": "2026-10-29T10:00:15Z",
            "waktu_isi_selesai": "2026-10-29T10:00:20Z",
            "waktu_tutup": "2026-10-29T10:00:25Z",
            "waktu_keluar": "2026-10-29T10:00:30Z",
            "level_isi": 0.55,
            "bertutup": True,
            "status": "TIDAK_PENUH",
        },
        {
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-prod-02",
            "pengguna": "haikal",
            "id_kirim": "btl-t4-03",
            "nomor": 3,
            "slot": 3,
            "waktu_masuk": "2026-10-29T10:01:00Z",
            "waktu_isi_mulai": "2026-10-29T10:01:05Z",
            "waktu_isi_selesai": "2026-10-29T10:01:10Z",
            "waktu_tutup": None,
            "waktu_keluar": "2026-10-29T10:01:15Z",
            "level_isi": 0.98,
            "bertutup": False,
            "status": "TANPA_TUTUP",
        },
    ]

    for b in botol_list:
        res = await client.post("/api/v1/botol", headers=auth_headers, json=b)
        assert res.status_code == 201

    # 2. Event Downtime E-Stop
    events_list = [
        {
            "waktu": "2026-10-29T10:00:12Z",
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-prod-01",
            "pengguna": "gibral",
            "jenis": "estop_tekan",
            "mode_sebelum": "Berjalan",
            "mode_sesudah": "Darurat",
            "sumber": "pemain",
            "pesan": "Emergency Stop ditekan karena botol miring",
        },
        {
            "waktu": "2026-10-29T10:00:22Z",
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-prod-01",
            "pengguna": "gibral",
            "jenis": "estop_lepas",
            "mode_sebelum": "Darurat",
            "mode_sesudah": "Siap",
            "sumber": "operator",
            "pesan": "Emergency Stop dilepas",
        },
    ]

    for ev in events_list:
        res = await client.post("/api/v1/event", headers=auth_headers, json=ev)
        assert res.status_code == 201


@pytest.mark.asyncio
async def test_ringkasan_produksi_dan_kualitas(client, seed_mes_data):
    """GET /api/mesin/{id}/ringkasan mengembalikan metrik Produksi dan Kualitas lengkap."""
    res = await client.get("/api/mesin/mesin-01/ringkasan")
    assert res.status_code == 200
    data = res.json()

    # Produksi
    assert data["jumlah_botol"] == 3
    assert data["rata_rata_waktu_siklus_detik"] == 15.0  # (10 + 20 + 15) / 3

    # Kualitas
    assert data["botol_ok"] == 1
    assert data["botol_gagal"] == 2
    assert data["kategori_kegagalan"]["TIDAK_PENUH"] == 1
    assert data["kategori_kegagalan"]["TANPA_TUTUP"] == 1

    # Downtime
    assert data["total_durasi_darurat_detik"] == 10.0

    # Rincian Pengguna
    assert "gibral" in data["rincian_pengguna"]
    assert data["rincian_pengguna"]["gibral"]["jumlah_botol"] == 2
    assert data["rincian_pengguna"]["gibral"]["botol_ok"] == 1
    assert data["rincian_pengguna"]["gibral"]["botol_gagal"] == 1
    assert data["rincian_pengguna"]["gibral"]["kategori_kegagalan"]["TIDAK_PENUH"] == 1
    assert data["rincian_pengguna"]["haikal"]["kategori_kegagalan"]["TANPA_TUTUP"] == 1


@pytest.mark.asyncio
async def test_traceability_daftar_botol_dan_filter(client, seed_mes_data):
    """GET /api/mesin/{id}/botol menguji pencarian, filter status, sesi, dan slot untuk Traceability."""
    # 1. Ambil seluruh botol
    res = await client.get("/api/mesin/mesin-01/botol")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 3
    # Verifikasi durasi siklus dihitung
    assert items[0]["durasi_siklus_detik"] is not None

    # 2. Filter status: OK
    res_ok = await client.get("/api/mesin/mesin-01/botol?status=OK")
    assert res_ok.status_code == 200
    ok_items = res_ok.json()
    assert len(ok_items) == 1
    assert ok_items[0]["status"] == "OK"
    assert ok_items[0]["nomor"] == 1

    # 3. Filter status: TIDAK_PENUH
    res_tp = await client.get("/api/mesin/mesin-01/botol?status=TIDAK_PENUH")
    assert res_tp.status_code == 200
    assert len(res_tp.json()) == 1
    assert res_tp.json()[0]["level_isi"] == 0.55

    # 4. Filter slot: 3
    res_slot = await client.get("/api/mesin/mesin-01/botol?slot=3")
    assert res_slot.status_code == 200
    assert len(res_slot.json()) == 1
    assert res_slot.json()[0]["slot"] == 3
    assert res_slot.json()[0]["bertutup"] is False

    # 5. Filter sesi_id
    res_sesi = await client.get("/api/mesin/mesin-01/botol?sesi_id=sesi-prod-01")
    assert res_sesi.status_code == 200
    assert len(res_sesi.json()) == 2

    # 6. Pagination dan header
    res_pag = await client.get("/api/mesin/mesin-01/botol?page=1&limit=2")
    assert res_pag.status_code == 200
    assert len(res_pag.json()) == 2
    assert res_pag.headers["X-Total-Count"] == "3"
    assert res_pag.headers["X-Limit"] == "2"
    assert res_pag.headers["X-Page"] == "1"

    # 7. Output wrap=true
    res_wrap = await client.get("/api/mesin/mesin-01/botol?wrap=true&limit=2")
    assert res_wrap.status_code == 200
    w = res_wrap.json()
    assert w["total"] == 3
    assert len(w["items"]) == 2


@pytest.mark.asyncio
async def test_traceability_detail_botol_by_nomor(client, seed_mes_data):
    """GET /api/mesin/{id}/botol/{nomor} mengembalikan detail inspeksi botol tunggal."""
    # 1. Botol nomor 1 ada
    res1 = await client.get("/api/mesin/mesin-01/botol/1")
    assert res1.status_code == 200
    b1 = res1.json()
    assert b1["nomor"] == 1
    assert b1["slot"] == 1
    assert b1["status"] == "OK"
    assert b1["level_isi"] == 1.0
    assert b1["bertutup"] is True
    assert b1["durasi_siklus_detik"] == 10.0

    # 2. Botol nomor 2 ada
    res2 = await client.get("/api/mesin/mesin-01/botol/2")
    assert res2.status_code == 200
    b2 = res2.json()
    assert b2["nomor"] == 2
    assert b2["status"] == "TIDAK_PENUH"
    assert b2["durasi_siklus_detik"] == 20.0

    # 3. Botol nomor 999 tidak ada -> 404
    res_none = await client.get("/api/mesin/mesin-01/botol/999")
    assert res_none.status_code == 404
    assert "tidak ditemukan" in res_none.json()["detail"]


@pytest.mark.asyncio
async def test_downtime_mesin_endpoint(client, seed_mes_data):
    """GET /api/mesin/{id}/downtime mengembalikan analisis riwayat dan durasi downtime."""
    res = await client.get("/api/mesin/mesin-01/downtime")
    assert res.status_code == 200
    d = res.json()
    assert d["mesin_id"] == "mesin-01"
    assert d["total_durasi_downtime_detik"] == 10.0
    assert d["jumlah_kejadian_downtime"] == 1
    assert len(d["kejadian"]) == 1
    assert d["kejadian"][0]["status"] == "SELESAI"
    assert d["kejadian"][0]["durasi_detik"] == 10.0
    assert "Emergency Stop ditekan" in d["kejadian"][0]["pesan"]


@pytest.mark.asyncio
async def test_laporan_terpadu_mesin(client, seed_mes_data):
    """GET /api/mesin/{id}/laporan menyajikan laporan terpadu Produksi, Kualitas, dan Downtime."""
    res = await client.get("/api/mesin/mesin-01/laporan")
    assert res.status_code == 200
    lap = res.json()

    assert lap["mesin_id"] == "mesin-01"

    # Produksi
    assert lap["produksi"]["total_botol"] == 3
    assert lap["produksi"]["rata_rata_waktu_siklus_detik"] == 15.0
    assert lap["produksi"]["total_waktu_siklus_detik"] == 45.0

    # Kualitas
    assert lap["kualitas"]["botol_ok"] == 1
    assert lap["kualitas"]["botol_gagal"] == 2
    assert lap["kualitas"]["persentase_ok"] == 33.33
    assert lap["kualitas"]["kategori_kegagalan"]["TIDAK_PENUH"] == 1
    assert lap["kualitas"]["kategori_kegagalan"]["TANPA_TUTUP"] == 1

    # Downtime
    assert lap["downtime"]["total_durasi_detik"] == 10.0
    assert lap["downtime"]["jumlah_kejadian"] == 1
