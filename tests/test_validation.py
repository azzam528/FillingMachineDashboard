"""Pengujian validasi skema data, tipe, enum, timestamp, dan pengguna."""

import pytest


@pytest.mark.asyncio
async def test_field_wajib_hilang_ditolak_400(client, auth_headers):
    """Payload dengan field wajib yang hilang harus ditolak HTTP 400 dengan daftar field."""
    # Data telemetri tanpa 'waktu' dan tanpa 'pengguna'
    payload = [
        {
            "mesin_id": "mesin-01",
            "sesi_id": "gibral-1",
            "darurat": False,
            "sudut_turret_deg": 36.0,
            "botol_selesai": 5,
            "isi_kotak": 2,
            "sisa_peti": 10,
        }
    ]
    res = await client.post("/api/telemetri", headers=auth_headers, json=payload)
    assert res.status_code == 400
    data = res.json()
    assert "errors" in data
    fields = [err["field"] for err in data["errors"]]
    assert any("waktu" in f for f in fields)
    assert any("pengguna" in f for f in fields)


@pytest.mark.asyncio
async def test_enum_salah_ditolak_400(client, auth_headers):
    """Nilai enum yang tidak sesuai skema harus ditolak HTTP 400."""
    # Event dengan sumber tidak valid
    payload_event = {
        "waktu": "2026-10-29T10:00:00Z",
        "mesin_id": "mesin-01",
        "sesi_id": "gibral-1",
        "pengguna": "gibral",
        "jenis": "START",
        "sumber": "robot_asing",  # tidak ada di enum pemain/sistem/operator/esp32
    }
    res_ev = await client.post("/api/event", headers=auth_headers, json=payload_event)
    assert res_ev.status_code == 400

    # Botol dengan status tidak valid
    payload_botol = {
        "mesin_id": "mesin-01",
        "sesi_id": "gibral-1",
        "pengguna": "gibral",
        "nomor": 1,
        "slot": 1,
        "waktu_masuk": "2026-10-29T10:00:00Z",
        "waktu_keluar": "2026-10-29T10:00:15Z",
        "level_isi": 0.8,
        "bertutup": True,
        "status": "PECAH",  # harus OK / TIDAK_PENUH / TANPA_TUTUP
    }
    res_botol = await client.post("/api/botol", headers=auth_headers, json=payload_botol)
    assert res_botol.status_code == 400


@pytest.mark.asyncio
async def test_timestamp_tanpa_zona_waktu_ditolak_400(client, auth_headers):
    """Timestamp naive tanpa informasi zona waktu harus ditolak HTTP 400."""
    payload = {
        "waktu": "2026-10-29T10:00:00",  # tidak ada 'Z' atau offset '+00:00'
        "mesin_id": "mesin-01",
        "sesi_id": "gibral-1",
        "pengguna": "gibral",
        "jenis": "START",
        "sumber": "pemain",
    }
    res = await client.post("/api/event", headers=auth_headers, json=payload)
    assert res.status_code == 400
    assert any("zona waktu" in err["pesan"] for err in res.json()["errors"])


@pytest.mark.asyncio
async def test_pengguna_tidak_ada_atau_tidak_sah_ditolak_400(client, auth_headers):
    """Pengguna di luar daftar yang sah (gibral, haikal, alvin, naya) harus ditolak 400."""
    # 1. Tanpa pengguna
    payload1 = {
        "waktu": "2026-10-29T10:00:00Z",
        "mesin_id": "mesin-01",
        "sesi_id": "sesi-1",
        "jenis": "START",
        "sumber": "pemain",
    }
    res1 = await client.post("/api/event", headers=auth_headers, json=payload1)
    assert res1.status_code == 400

    # 2. Pengguna tidak terdaftar
    payload2 = {
        "waktu": "2026-10-29T10:00:00Z",
        "mesin_id": "mesin-01",
        "sesi_id": "sesi-1",
        "pengguna": "budi_santoso",
        "jenis": "START",
        "sumber": "pemain",
    }
    res2 = await client.post("/api/event", headers=auth_headers, json=payload2)
    assert res2.status_code == 400
    assert any("Pengguna 'budi_santoso' tidak sah" in err["pesan"] for err in res2.json()["errors"])


@pytest.mark.asyncio
async def test_pengguna_normalisasi_huruf_kecil_sukses(client, auth_headers):
    """Pengguna huruf besar/campuran dinormalisasi ke huruf kecil dan diterima."""
    payload = {
        "waktu": "2026-10-29T10:00:00Z",
        "mesin_id": "mesin-01",
        "sesi_id": "gibral-sesi-1",
        "pengguna": "  GiBrAl  ",
        "jenis": "START",
        "sumber": "pemain",
    }
    res = await client.post("/api/event", headers=auth_headers, json=payload)
    assert res.status_code == 201
    assert res.json()["tersimpan"] is True


@pytest.mark.asyncio
async def test_botol_timestamps_non_monotonic_ditolak_400(client, auth_headers):
    """Urutan waktu botol yang tidak menaik harus ditolak HTTP 400."""
    payload = {
        "mesin_id": "mesin-01",
        "sesi_id": "gibral-1",
        "pengguna": "gibral",
        "nomor": 1,
        "slot": 1,
        "waktu_masuk": "2026-10-29T10:00:20Z",
        "waktu_isi_mulai": "2026-10-29T10:00:15Z",  # lebih awal dari waktu_masuk
        "waktu_keluar": "2026-10-29T10:00:25Z",
        "level_isi": 0.88,
        "bertutup": True,
        "status": "OK",
    }
    res = await client.post("/api/botol", headers=auth_headers, json=payload)
    assert res.status_code == 400
    assert any("Urutan timestamp botol harus menaik" in err["pesan"] for err in res.json().get("errors", []))


@pytest.mark.asyncio
async def test_telemetri_botol_count_mismatch_ditolak_400(client, auth_headers):
    """Telemetri dengan botol_selesai != botol_ok + botol_reject harus ditolak HTTP 400."""
    payload = [
        {
            "waktu": "2026-10-29T10:00:00Z",
            "mesin_id": "mesin-01",
            "sesi_id": "gibral-1",
            "pengguna": "gibral",
            "botol_selesai": 30,
            "botol_ok": 20,
            "botol_reject": 5,  # 20 + 5 != 30
        }
    ]
    res = await client.post("/api/telemetri", headers=auth_headers, json=payload)
    assert res.status_code == 400
    assert any("botol_selesai" in err["pesan"] for err in res.json().get("errors", []))


@pytest.mark.asyncio
async def test_telemetri_tahap_string_dan_int_diterima(client, auth_headers):
    """Tahap telemetri menerima format string maupun int."""
    payload = [
        {
            "waktu": "2026-10-29T10:00:00Z",
            "mesin_id": "mesin-01",
            "sesi_id": "gibral-1",
            "pengguna": "gibral",
            "tahap": "Mengisi + Memasang tutup",
        },
        {
            "waktu": "2026-10-29T10:00:02Z",
            "mesin_id": "mesin-01",
            "sesi_id": "gibral-1",
            "pengguna": "gibral",
            "tahap": 3,
        },
    ]
    res = await client.post("/api/telemetri", headers=auth_headers, json=payload)
    assert res.status_code == 201
    assert res.json()["tersimpan"] == 2



@pytest.mark.asyncio
async def test_mesin_id_tidak_dikenal_ditolak_400(client, auth_headers):
    """mesin_id yang tidak ada di collection mesin harus ditolak HTTP 400."""
    payload = {
        "waktu": "2026-10-29T10:00:00Z",
        "mesin_id": "mesin-tidak-ada-999",
        "sesi_id": "gibral-1",
        "pengguna": "gibral",
        "jenis": "START",
        "sumber": "pemain",
    }
    res = await client.post("/api/event", headers=auth_headers, json=payload)
    assert res.status_code == 400
    assert "tidak terdaftar" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_field_tambahan_diizinkan_sukses(client, auth_headers):
    """Field tambahan yang tidak dikenal harus diizinkan (kompatibilitas skema v1)."""
    payload = {
        "waktu": "2026-10-29T10:00:00Z",
        "mesin_id": "mesin-01",
        "sesi_id": "gibral-1",
        "pengguna": "gibral",
        "jenis": "START",
        "sumber": "pemain",
        "field_ekstra_unity": "fitur_eksperimental",
        "suhu_motor_celsius": 42.5,
    }
    res = await client.post("/api/event", headers=auth_headers, json=payload)
    assert res.status_code == 201
    assert res.json()["tersimpan"] is True


@pytest.mark.asyncio
async def test_botol_timestamps_non_monotonic_ditolak_400(client, auth_headers):
    """Urutan waktu botol yang tidak menaik harus ditolak HTTP 400."""
    payload = {
        "mesin_id": "mesin-01",
        "sesi_id": "gibral-1",
        "pengguna": "gibral",
        "nomor": 1,
        "slot": 1,
        "waktu_masuk": "2026-10-29T10:00:20Z",
        "waktu_isi_mulai": "2026-10-29T10:00:15Z",  # lebih awal dari waktu_masuk
        "waktu_keluar": "2026-10-29T10:00:25Z",
        "level_isi": 0.88,
        "bertutup": True,
        "status": "OK",
    }
    res = await client.post("/api/botol", headers=auth_headers, json=payload)
    assert res.status_code == 400
    assert any("Urutan timestamp botol harus menaik" in err["pesan"] for err in res.json().get("errors", []))


@pytest.mark.asyncio
async def test_telemetri_botol_count_mismatch_ditolak_400(client, auth_headers):
    """Telemetri dengan botol_selesai != botol_ok + botol_reject harus ditolak HTTP 400."""
    payload = [
        {
            "waktu": "2026-10-29T10:00:00Z",
            "mesin_id": "mesin-01",
            "sesi_id": "gibral-1",
            "pengguna": "gibral",
            "botol_selesai": 30,
            "botol_ok": 20,
            "botol_reject": 5,  # 20 + 5 != 30
        }
    ]
    res = await client.post("/api/telemetri", headers=auth_headers, json=payload)
    assert res.status_code == 400
    assert any("botol_selesai" in err["pesan"] for err in res.json().get("errors", []))


@pytest.mark.asyncio
async def test_telemetri_tahap_string_dan_int_diterima(client, auth_headers):
    """Tahap telemetri menerima format string maupun int."""
    payload = [
        {
            "waktu": "2026-10-29T10:00:00Z",
            "mesin_id": "mesin-01",
            "sesi_id": "gibral-1",
            "pengguna": "gibral",
            "tahap": "Mengisi + Memasang tutup",
        },
        {
            "waktu": "2026-10-29T10:00:02Z",
            "mesin_id": "mesin-01",
            "sesi_id": "gibral-1",
            "pengguna": "gibral",
            "tahap": 3,
        },
    ]
    res = await client.post("/api/telemetri", headers=auth_headers, json=payload)
    assert res.status_code == 201
    assert res.json()["tersimpan"] == 2

