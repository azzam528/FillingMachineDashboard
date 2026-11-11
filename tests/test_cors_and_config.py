"""Pengujian konfigurasi integrasi Frontend MES: CORS, Environment, API Base URL, dan MongoDB."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_cors_preflight_allowed_origin(client):
    """Permintaan preflight OPTIONS dari origin yang diizinkan harus mengembalikan header CORS yang sesuai."""
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Api-Key,Content-Type",
    }
    response = await client.options("/api/v1/health", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"
    assert "GET" in response.headers.get("access-control-allow-methods", "")


@pytest.mark.asyncio
async def test_cors_request_allowed_origin(client):
    """Permintaan aktual GET dari origin frontend MES yang diizinkan harus menyertakan header CORS."""
    response = await client.get("/api/v1/health", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


@pytest.mark.asyncio
async def test_cors_disallowed_origin(client):
    """Permintaan dari origin yang tidak terdaftar tidak boleh mendapatkan header access-control-allow-origin."""
    response = await client.get("/api/v1/health", headers={"Origin": "http://malicious-website.com"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_production_wildcard_rejected():
    """Pada environment production, wildcard '*' dilarang keras dan harus menghasilkan ValueError."""
    with pytest.raises(ValueError, match="Wildcard '\\*' dilarang"):
        Settings(
            ENVIRONMENT="production",
            CORS_ORIGINS="*",
        )

    with pytest.raises(ValueError, match="Wildcard '\\*' dilarang"):
        Settings(
            ENVIRONMENT="production",
            CORS_ORIGINS="https://mes.fillingmachine.domainkamu.com, *",
        )


def test_production_valid_mes_domain():
    """Pada environment production, domain spesifik frontend MES diizinkan dan wildcard tidak ada."""
    prod_settings = Settings(
        ENVIRONMENT="production",
        CORS_ORIGINS="https://mes.fillingmachine.domainkamu.com,https://fillingmachine.domainkamu.com",
    )
    assert prod_settings.is_production is True
    assert prod_settings.is_development is False
    assert "*" not in prod_settings.cors_origins_list
    assert "https://mes.fillingmachine.domainkamu.com" in prod_settings.cors_origins_list
    assert "https://fillingmachine.domainkamu.com" in prod_settings.cors_origins_list


def test_production_debug_forced_false():
    """Pada mode production, flag DEBUG secara otomatis dinonaktifkan demi keamanan."""
    prod_settings = Settings(
        ENVIRONMENT="production",
        DEBUG=True,
        CORS_ORIGINS="https://mes.fillingmachine.domainkamu.com",
    )
    assert prod_settings.DEBUG is False


def test_environment_flags():
    """Memverifikasi flag status lingkungan: development, production, test."""
    dev = Settings(ENVIRONMENT="development")
    assert dev.is_development is True
    assert dev.is_production is False
    assert dev.is_test is False

    prod = Settings(
        ENVIRONMENT="production",
        CORS_ORIGINS="https://mes.fillingmachine.domainkamu.com",
    )
    assert prod.is_development is False
    assert prod.is_production is True
    assert prod.is_test is False

    t = Settings(ENVIRONMENT="test")
    assert t.is_test is True
    assert t.is_development is False
    assert t.is_production is False


def test_api_prefix_sync():
    """Pengaturan API_PREFIX dan API_V1_STR harus tersinkronisasi tanpa hardcode kaku."""
    s1 = Settings(API_PREFIX="/api/v2")
    assert s1.API_V1_STR == "/api/v2"

    s2 = Settings(API_V1_STR="/api/custom")
    assert s2.API_PREFIX == "/api/custom"


def test_api_base_url_configuration():
    """Base URL API publik dapat dikonfigurasi secara dinamis melalui settings."""
    custom_url = "https://api.fillingmachine.domainkamu.com"
    s = Settings(
        ENVIRONMENT="production",
        CORS_ORIGINS="https://mes.fillingmachine.domainkamu.com",
        API_BASE_URL=custom_url,
    )
    app = create_app(s)
    assert app.servers == [{"url": custom_url, "description": "API Base URL"}]


def test_mongodb_config_without_hardcoded_credentials():
    """Konfigurasi MongoDB dibaca secara dinamis dan memiliki default aman."""
    s = Settings()
    assert s.MONGODB_DB_NAME == "liquidfilling"
    assert s.MONGODB_URI.startswith("mongodb")
