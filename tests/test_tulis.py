"""Pengujian endpoint tulis: telemetri (batch + dedup), event (dedup), botol (dedup)."""

import pytest


def buat_payload_telemetri(nomor: int, pengguna: str = "gibral", id_kirim: str = None) -> dict:
    return {
        "waktu": f"2026-10-29T10:00:{nomor:02d}Z",
        "mesin_id": "mesin-01",
        "sesi_id": f"{pengguna}-sesi-1",
        "pengguna": pengguna,
        "id_kirim": id_kirim,
        "mode": "Berjalan",
        "darurat": False,
        "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
        "tahap": 1,
        "langkah": 2,
        "sudut_turret_deg": float(nomor * 36 % 360),
        "botol_selesai": nomor,
        "isi_kotak": nomor % 30,
        "sisa_peti": 100 - nomor,
        "operator_tugas": "memantau",
        "gpio": {"step": True, "dir": False, "en": True, "pompa": False, "buzzer": False, "ir": True, "start": False, "limit": False},
    }


@pytest.mark.asyncio
async def test_post_telemetri_valid_201(client, auth_headers, test_db):
    """Menyimpan 1 data telemetri valid dan memverifikasi field server 'diterima'."""
    payload = [buat_payload_telemetri(1, "gibral", id_kirim="tel-001")]
    res = await client.post("/api/v1/telemetri", headers=auth_headers, json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "sukses"
    assert data["tersimpan"] == 1
    assert data["duplikat_diabaikan"] == 0

    # Cek dokumen di database
    doc = await test_db.telemetri.find_one({"id_kirim": "tel-001"})
    assert doc is not None
    assert "diterima" in doc
    assert doc["pengguna"] == "gibral"


@pytest.mark.asyncio
async def test_post_telemetri_batch_maksimal_10_sukses(client, auth_headers):
    """Batch maksimal 10 data telemetri berhasil disimpan sekaligus."""
    payload = [buat_payload_telemetri(i, "haikal", id_kirim=f"tel-batch-{i}") for i in range(1, 11)]
    res = await client.post("/api/v1/telemetri", headers=auth_headers, json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["tersimpan"] == 10
    assert data["duplikat_diabaikan"] == 0


@pytest.mark.asyncio
async def test_post_telemetri_batch_lebih_dari_10_ditolak_400(client, auth_headers):
    """Batch lebih dari 10 data telemetri harus ditolak HTTP 400."""
    payload = [buat_payload_telemetri(i, "alvin", id_kirim=f"tel-over-{i}") for i in range(1, 12)]
    res = await client.post("/api/v1/telemetri", headers=auth_headers, json=payload)
    assert res.status_code == 400
    assert "antara 1 sampai 10" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_post_telemetri_batch_kosong_ditolak_400(client, auth_headers):
    """Batch kosong [] harus ditolak HTTP 400."""
    res = await client.post("/api/v1/telemetri", headers=auth_headers, json=[])
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_post_telemetri_dedup_id_kirim(client, auth_headers):
    """Telemetri dengan id_kirim yang sudah ada tidak dimasukkan ulang (deduplikasi API)."""
    # 1. Kirim dokumen pertama
    doc1 = buat_payload_telemetri(1, "naya", id_kirim="tel-dedup-1")
    res1 = await client.post("/api/v1/telemetri", headers=auth_headers, json=[doc1])
    assert res1.status_code == 201
    assert res1.json()["tersimpan"] == 1

    # 2. Kirim ulang doc1 bersama doc2
    doc2 = buat_payload_telemetri(2, "naya", id_kirim="tel-dedup-2")
    res2 = await client.post("/api/v1/telemetri", headers=auth_headers, json=[doc1, doc2])
    assert res2.status_code == 201
    data2 = res2.json()
    assert data2["tersimpan"] == 1
    assert data2["duplikat_diabaikan"] == 1


@pytest.mark.asyncio
async def test_post_event_valid_dan_dedup(client, auth_headers, test_db):
    """Menyimpan event dan menguji idempotensi saat id_kirim duplikat dikirim ulang."""
    payload = {
        "waktu": "2026-10-29T10:05:00Z",
        "mesin_id": "mesin-01",
        "sesi_id": "gibral-sesi-1",
        "pengguna": "gibral",
        "id_kirim": "ev-unique-001",
        "jenis": "estop_tekan",
        "sumber": "pemain",
        "pesan": "Tombol e-stop ditekan pemain",
    }
    # 1. Kirim pertama -> 201 tersimpan
    res1 = await client.post("/api/v1/event", headers=auth_headers, json=payload)
    assert res1.status_code == 201
    data1 = res1.json()
    assert data1["tersimpan"] is True
    assert data1["id"] is not None

    # Verifikasi diterima tersimpan di db
    doc = await test_db.event.find_one({"id_kirim": "ev-unique-001"})
    assert doc is not None
    assert "diterima" in doc

    # 2. Kirim ulang dengan id_kirim yang sama -> 201 duplikat diabaikan (idempotent)
    res2 = await client.post("/api/v1/event", headers=auth_headers, json=payload)
    assert res2.status_code == 201
    data2 = res2.json()
    assert data2["tersimpan"] is False
    assert data2["pesan"] == "duplikat diabaikan"


@pytest.mark.asyncio
async def test_post_botol_valid_dan_dedup(client, auth_headers, test_db):
    """Menyimpan botol dan menguji idempotensi saat id_kirim duplikat dikirim ulang."""
    payload = {
        "mesin_id": "mesin-01",
        "sesi_id": "haikal-sesi-1",
        "pengguna": "haikal",
        "id_kirim": "btl-unique-001",
        "nomor": 1,
        "slot": 3,
        "waktu_masuk": "2026-10-29T10:00:00Z",
        "waktu_isi_mulai": "2026-10-29T10:00:03Z",
        "waktu_isi_selesai": "2026-10-29T10:00:08Z",
        "waktu_tutup": "2026-10-29T10:00:11Z",
        "waktu_keluar": "2026-10-29T10:00:14Z",
        "level_isi": 0.98,
        "bertutup": True,
        "status": "OK",
    }
    # 1. Kirim pertama -> 201 tersimpan
    res1 = await client.post("/api/v1/botol", headers=auth_headers, json=payload)
    assert res1.status_code == 201
    data1 = res1.json()
    assert data1["tersimpan"] is True

    # 2. Kirim ulang dengan id_kirim yang sama -> 201 duplikat diabaikan (idempotent)
    res2 = await client.post("/api/v1/botol", headers=auth_headers, json=payload)
    assert res2.status_code == 201
    data2 = res2.json()
    assert data2["tersimpan"] is False
    assert data2["pesan"] == "duplikat diabaikan"

