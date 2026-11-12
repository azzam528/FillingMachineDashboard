"""Pengujian endpoint health check."""

import pytest


@pytest.mark.asyncio
async def test_health_check_sukses(client):
    """GET /health dan /api/health harus mengembalikan 200 saat database terhubung."""
    res1 = await client.get("/api/health")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "ok"
    assert data1["database"] == "terhubung"
    assert "waktu" in data1

    # Cek root path /health
    res2 = await client.get("/health")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "ok"


@pytest.mark.asyncio
async def test_endpoint_lama_v1_tidak_tersedia(client):
    """Endpoint dengan prefix lama /api/v1 tidak lagi tersedia (harus mengembalikan 404)."""
    endpoints_lama = [
        "/api/v1/health",
        "/api/v1/telemetri",
        "/api/v1/event",
        "/api/v1/botol",
        "/api/v1/mesin/mesin-01",
        "/api/v1/mesin/mesin-01/status",
        "/api/v1/mesin/mesin-01/ringkasan",
        "/api/v1/mesin/mesin-01/event",
    ]
    for url in endpoints_lama:
        res = await client.get(url)
        assert res.status_code == 404, f"Endpoint {url} seharusnya 404 Not Found"
