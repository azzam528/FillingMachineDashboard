"""Pengujian komprehensif endpoint Live Monitoring backend MES:
- GET /api/mesin/{id} dan GET /api/v1/mesin/{id}
- GET /api/mesin/{id}/status dan GET /api/v1/mesin/{id}/status
- GET /api/mesin/{id}/event dan GET /api/v1/mesin/{id}/event
"""

import pytest


@pytest.mark.asyncio
async def test_get_konfigurasi_mesin_lengkap(client):
    """GET /api/mesin/{id} dan /api/v1/mesin/{id} mengembalikan informasi konfigurasi mesin lengkap."""
    # 1. Akses via prefix /api
    res_api = await client.get("/api/mesin/mesin-01")
    assert res_api.status_code == 200
    cfg = res_api.json()
    assert cfg["_id"] == "mesin-01"
    assert cfg["jumlah_slot"] == 10
    assert cfg["sudut_per_slot_deg"] == 36
    assert "stasiun" in cfg
    assert cfg["stasiun"]["infeed"] == 36
    assert cfg["stasiun"]["isi"] == 180
    assert cfg["stasiun"]["capping"] == 144
    assert cfg["stasiun"]["buang"] == 108
    assert cfg["kapasitas_kotak"] == 30
    assert cfg["kapasitas_peti"] == 12
    assert "pin_gpio" in cfg
    assert "step" in cfg["pin_gpio"]
    assert "pompa" in cfg["pin_gpio"]

    # 2. Akses via prefix /api/v1
    res_v1 = await client.get("/api/v1/mesin/mesin-01")
    assert res_v1.status_code == 200
    assert res_v1.json()["_id"] == "mesin-01"

    # 3. Mesin tidak ditemukan -> 404
    res_404 = await client.get("/api/mesin/mesin-tidak-ada")
    assert res_404.status_code == 404
    assert "tidak ditemukan" in res_404.json()["detail"]


@pytest.mark.asyncio
async def test_get_daftar_seluruh_mesin(client):
    """GET /api/mesin mengembalikan seluruh daftar mesin yang terdaftar."""
    res = await client.get("/api/mesin")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert any(m["_id"] == "mesin-01" for m in data)


@pytest.mark.asyncio
async def test_live_monitoring_status_telemetri_lengkap(client, auth_headers):
    """GET /api/mesin/{id}/status mengembalikan seluruh 9 kebutuhan live monitoring:
    mode, MCB, sudut turret, botol selesai, GPIO, tahap dan langkah, darurat, dll.
    """
    # Kirim data telemetri pertama (t0)
    await client.post(
        "/api/v1/telemetri",
        headers=auth_headers,
        json=[
            {
                "waktu": "2026-10-29T10:00:00Z",
                "mesin_id": "mesin-01",
                "sesi_id": "sesi-live-01",
                "pengguna": "gibral",
                "mode": "Siap",
                "darurat": False,
                "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": False},
                "tahap": 1,
                "langkah": 1,
                "sudut_turret_deg": 0.0,
                "botol_selesai": 0,
                "isi_kotak": 0,
                "sisa_peti": 12,
                "operator_tugas": "Persiapan infeed",
                "gpio": {
                    "step": 0,
                    "dir": 0,
                    "en": 1,
                    "pompa": 0,
                    "buzzer": 0,
                    "ir": 1,
                    "start": 0,
                    "limit": 0,
                },
            }
        ],
    )

    # Kirim data telemetri kedua (t1 - lebih baru, mode Berjalan, MCB lampu aktif, botol bertambah)
    await client.post(
        "/api/v1/telemetri",
        headers=auth_headers,
        json=[
            {
                "waktu": "2026-10-29T10:00:05Z",
                "mesin_id": "mesin-01",
                "sesi_id": "sesi-live-01",
                "pengguna": "gibral",
                "mode": "Berjalan",
                "darurat": False,
                "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
                "tahap": "Pengisian",
                "langkah": 3,
                "sudut_turret_deg": 180.0,
                "botol_selesai": 5,
                "isi_kotak": 5,
                "sisa_peti": 7,
                "operator_tugas": "Memantau nosel pengisi",
                "gpio": {
                    "step": 1,
                    "dir": 0,
                    "en": 1,
                    "pompa": 1,
                    "buzzer": 0,
                    "ir": 0,
                    "start": 1,
                    "limit": 0,
                },
            }
        ],
    )

    # Uji pembacaan via /api/mesin/{id}/status
    res = await client.get("/api/mesin/mesin-01/status")
    assert res.status_code == 200
    st = res.json()

    # Verifikasi seluruh parameter Live Monitoring
    assert st["mesin_id"] == "mesin-01"
    assert st["sesi_id"] == "sesi-live-01"
    assert st["pengguna"] == "gibral"
    assert st["waktu"] == "2026-10-29T10:00:05Z"
    assert st["mode"] == "Berjalan"
    assert st["darurat"] is False
    assert st["mcb"] == {"utama": True, "mesin": True, "kontrol": True, "lampu": True}
    assert st["sudut_turret_deg"] == 180.0
    assert st["botol_selesai"] == 5
    assert st["isi_kotak"] == 5
    assert st["sisa_peti"] == 7
    assert st["tahap"] == "Pengisian"
    assert st["langkah"] == 3
    assert st["operator_tugas"] == "Memantau nosel pengisi"
    assert st["gpio"]["pompa"] == 1
    assert st["gpio"]["step"] == 1

    # Uji filter sesi_id pada /api/mesin/{id}/status
    res_sesi = await client.get("/api/mesin/mesin-01/status?sesi_id=sesi-live-01")
    assert res_sesi.status_code == 200
    assert res_sesi.json()["sesi_id"] == "sesi-live-01"

    # Uji filter sesi_id yang tidak ada -> 404
    res_sesi_none = await client.get("/api/mesin/mesin-01/status?sesi_id=sesi-fiktif")
    assert res_sesi_none.status_code == 404


@pytest.mark.asyncio
async def test_live_monitoring_event_sorting_and_filters(client, auth_headers):
    """GET /api/mesin/{id}/event menguji sorting waktu desc, filter jenis koma, sesi, sumber, dan mode."""
    events_data = [
        {
            "waktu": "2026-10-29T09:00:00Z",
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-ev-1",
            "pengguna": "alvin",
            "jenis": "START",
            "mode_sebelum": "Siap",
            "mode_sesudah": "Berjalan",
            "sumber": "operator",
            "pesan": "Mesin dinyalakan",
        },
        {
            "waktu": "2026-10-29T09:10:00Z",
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-ev-1",
            "pengguna": "alvin",
            "jenis": "estop_tekan",
            "mode_sebelum": "Berjalan",
            "mode_sesudah": "Darurat",
            "sumber": "pemain",
            "pesan": "E-stop ditekan saat botol miring",
        },
        {
            "waktu": "2026-10-29T09:15:00Z",
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-ev-1",
            "pengguna": "alvin",
            "jenis": "estop_lepas",
            "mode_sebelum": "Darurat",
            "mode_sesudah": "Siap",
            "sumber": "operator",
            "pesan": "E-stop dilepas setelah penanganan",
        },
        {
            "waktu": "2026-10-29T09:20:00Z",
            "mesin_id": "mesin-01",
            "sesi_id": "sesi-ev-2",
            "pengguna": "naya",
            "jenis": "MCB_OFF",
            "mode_sebelum": "Siap",
            "mode_sesudah": "Mati",
            "sumber": "sistem",
            "pesan": "MCB dimatikan otomatis",
        },
    ]

    for ev in events_data:
        await client.post("/api/v1/event", headers=auth_headers, json=ev)

    # 1. Pastikan sorting terbaru lebih dulu (09:20:00)
    res = await client.get("/api/mesin/mesin-01/event")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 4
    assert items[0]["waktu"] == "2026-10-29T09:20:00Z"
    assert items[0]["jenis"] == "MCB_OFF"
    assert items[-1]["waktu"] == "2026-10-29T09:00:00Z"

    # 2. Filter jenis dipisahkan koma: 'estop_tekan,estop_lepas'
    res_comma = await client.get("/api/mesin/mesin-01/event?jenis=estop_tekan,estop_lepas")
    assert res_comma.status_code == 200
    comma_items = res_comma.json()
    assert len(comma_items) == 2
    assert {i["jenis"] for i in comma_items} == {"estop_tekan", "estop_lepas"}

    # 3. Filter sumber: 'operator'
    res_sumber = await client.get("/api/mesin/mesin-01/event?sumber=operator")
    assert res_sumber.status_code == 200
    sumber_items = res_sumber.json()
    assert len(sumber_items) == 2
    assert all(i["sumber"] == "operator" for i in sumber_items)

    # 4. Filter mode: 'Darurat'
    res_mode = await client.get("/api/mesin/mesin-01/event?mode=Darurat")
    assert res_mode.status_code == 200
    mode_items = res_mode.json()
    assert len(mode_items) == 2  # estop_tekan (sesudah=Darurat) & estop_lepas (sebelum=Darurat)

    # 5. Filter rentang waktu: 09:05:00 s.d 09:16:00
    res_time = await client.get(
        "/api/mesin/mesin-01/event?dari=2026-10-29T09:05:00Z&sampai=2026-10-29T09:16:00Z"
    )
    assert res_time.status_code == 200
    time_items = res_time.json()
    assert len(time_items) == 2
    assert [i["jenis"] for i in time_items] == ["estop_lepas", "estop_tekan"]

    # 6. Rentang waktu tidak valid (dari > sampai) -> 400
    res_invalid_time = await client.get(
        "/api/mesin/mesin-01/event?dari=2026-10-29T10:00:00Z&sampai=2026-10-29T09:00:00Z"
    )
    assert res_invalid_time.status_code == 400


@pytest.mark.asyncio
async def test_live_monitoring_event_pagination_and_headers(client, auth_headers):
    """GET /api/mesin/{id}/event menguji pagination page/skip/limit, header respons, dan wrap=true."""
    # Kirim 4 event data pengujian
    for i in range(4):
        await client.post(
            "/api/v1/event",
            headers=auth_headers,
            json={
                "waktu": f"2026-10-29T11:0{i}:00Z",
                "mesin_id": "mesin-01",
                "sesi_id": "sesi-pag",
                "pengguna": "haikal",
                "jenis": f"EVENT_{i}",
                "sumber": "sistem",
            },
        )

    # Page 1 (limit 2)
    res_page = await client.get("/api/mesin/mesin-01/event?page=1&limit=2")
    assert res_page.status_code == 200
    p1_items = res_page.json()
    assert len(p1_items) == 2
    assert p1_items[0]["waktu"] == "2026-10-29T11:03:00Z"

    # Verifikasi header pagination
    assert res_page.headers["X-Total-Count"] == "4"
    assert res_page.headers["X-Limit"] == "2"
    assert res_page.headers["X-Page"] == "1"
    assert res_page.headers["X-Skip"] == "0"
    assert res_page.headers["X-Total-Pages"] == "2"

    # Page 2 (limit 2)
    res_p2 = await client.get("/api/mesin/mesin-01/event?page=2&limit=2")
    assert res_p2.status_code == 200
    p2_items = res_p2.json()
    assert len(p2_items) == 2
    assert res_p2.headers["X-Page"] == "2"
    assert res_p2.headers["X-Skip"] == "2"
    # Pastikan data page 1 dan page 2 tidak saling tumpang tindih
    assert p1_items[0]["waktu"] != p2_items[0]["waktu"]
    assert p2_items[0]["waktu"] == "2026-10-29T11:01:00Z"

    # Uji wrap=true untuk mendapatkan format objek dengan metadata lengkap
    res_wrap = await client.get("/api/mesin/mesin-01/event?wrap=true&limit=2")
    assert res_wrap.status_code == 200
    wrapped = res_wrap.json()
    assert isinstance(wrapped, dict)
    assert wrapped["total"] == 4
    assert wrapped["page"] == 1
    assert wrapped["limit"] == 2
    assert wrapped["total_pages"] == 2
    assert "items" in wrapped
    assert len(wrapped["items"]) == 2
