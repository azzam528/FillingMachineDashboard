"""Pengujian autentikasi X-Api-Key dan otorisasi."""

import pytest
from app.config import Settings, get_settings
from app.main import app

VALID_KEY = "test-secret-key-12345"


@pytest.mark.asyncio
async def test_tulis_tanpa_api_key(client):
    """Endpoint tulis tanpa header X-Api-Key harus mengembalikan 401 Unauthorized."""
    payload = {
        "waktu": "2026-10-29T10:00:00Z",
        "mesin_id": "mesin-01",
        "sesi_id": "gibral-20261029-1000",
        "pengguna": "gibral",
        "jenis": "estop_tekan",
        "sumber": "pemain",
    }
    response = await client.post("/api/v1/event", json=payload)
    assert response.status_code == 401
    assert "X-Api-Key" in response.json().get("detail", "")


@pytest.mark.asyncio
async def test_tulis_api_key_salah(client):
    """Endpoint tulis dengan header X-Api-Key yang salah harus mengembalikan 401."""
    payload = {
        "waktu": "2026-10-29T10:00:00Z",
        "mesin_id": "mesin-01",
        "sesi_id": "gibral-20261029-1000",
        "pengguna": "gibral",
        "jenis": "estop_tekan",
        "sumber": "pemain",
    }
    response = await client.post(
        "/api/v1/event",
        headers={"X-Api-Key": "kunci-salah-palsu"},
        json=payload,
    )
    assert response.status_code == 401
    assert "API Key tidak valid" in response.json().get("detail", "")


@pytest.mark.asyncio
async def test_baca_require_key_false(client):
    """Saat REQUIRE_KEY_FOR_READ=False, endpoint GET dapat diakses publik tanpa API Key."""
    response = await client.get("/api/v1/mesin/mesin-01")
    assert response.status_code == 200
    assert response.json()["_id"] == "mesin-01"


@pytest.mark.asyncio
async def test_baca_require_key_true(client, test_settings):
    """Saat REQUIRE_KEY_FOR_READ=True, endpoint GET wajib menyertakan API Key yang valid."""
    read_restricted_settings = Settings(
        MONGODB_URI=test_settings.MONGODB_URI,
        MONGODB_DB_NAME=test_settings.MONGODB_DB_NAME,
        API_KEY=VALID_KEY,
        REQUIRE_KEY_FOR_READ=True,
        PENGGUNA_VALID="gibral,haikal,alvin,naya",
    )
    app.dependency_overrides[get_settings] = lambda: read_restricted_settings

    # 1. Tanpa header -> 401
    res1 = await client.get("/api/v1/mesin/mesin-01")
    assert res1.status_code == 401

    # 2. Key salah -> 401
    res2 = await client.get(
        "/api/v1/mesin/mesin-01",
        headers={"X-Api-Key": "kunci-salah"},
    )
    assert res2.status_code == 401

    # 3. Key benar -> 200
    res3 = await client.get(
        "/api/v1/mesin/mesin-01",
        headers={"X-Api-Key": VALID_KEY},
    )
    assert res3.status_code == 200
    assert res3.json()["_id"] == "mesin-01"

