"""Pengujian endpoint health check."""

import pytest


@pytest.mark.asyncio
async def test_health_check_sukses(client):
    """GET /health dan /api/v1/health harus mengembalikan 200 saat database terhubung."""
    res1 = await client.get("/api/v1/health")
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
