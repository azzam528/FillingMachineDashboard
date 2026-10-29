"""Pytest fixtures untuk pengujian REST API menggunakan database terpisah liquidfilling_test."""

from typing import AsyncGenerator
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.config import Settings, get_settings
from app.db import db_instance, get_db
from app.main import app
from setup_mongodb import BOTOL, EVENT, MESIN, MESIN_01

TEST_API_KEY = "test-secret-key-12345"


@pytest.fixture
def test_settings() -> Settings:
    """Settings khusus pengujian."""
    return Settings(
        MONGODB_URI="mongodb://localhost:27017",
        MONGODB_DB_NAME="liquidfilling_test",
        API_KEY=TEST_API_KEY,
        REQUIRE_KEY_FOR_READ=False,
        PENGGUNA_VALID="gibral,haikal,alvin,naya",
        EVENT_JENIS_ESTOP_TEKAN="estop_tekan",
        EVENT_JENIS_ESTOP_LEPAS="estop_lepas",
    )


async def _safe_create_collection(db, name: str, **kwargs):
    """Membuat collection dengan validator/opsi jika didukung database engine (mis. MongoDB asli),
    atau fallback tanpa kwargs jika menggunakan mongomock."""
    try:
        await db.create_collection(name, **kwargs)
    except (NotImplementedError, Exception):
        if name not in await db.list_collection_names():
            await db.create_collection(name)


@pytest.fixture
async def test_db():
    """Fixture database liquidfilling_test yang diisolasi dengan collection dan index yang sama seperti setup_mongodb.py."""
    mock_client = AsyncMongoMockClient()
    db = mock_client["liquidfilling_test"]

    # 1. mesin: buat dan masukkan mesin-01
    await _safe_create_collection(db, "mesin", validator=MESIN)
    await db.mesin.update_one(
        {"_id": "mesin-01"},
        {"$setOnInsert": MESIN_01},
        upsert=True,
    )

    # 2. telemetri
    await _safe_create_collection(db, "telemetri")

    # 3. event
    await _safe_create_collection(db, "event", validator=EVENT)
    try:
        await db.event.create_index(
            [("mesin_id", 1), ("waktu", -1)], name="mesin_waktu"
        )
        await db.event.create_index(
            [("mesin_id", 1), ("sesi_id", 1)], name="mesin_sesi"
        )
        await db.event.create_index(
            [("id_kirim", 1)],
            name="id_kirim_unik",
            unique=True,
            partialFilterExpression={"id_kirim": {"$type": "string"}},
        )
    except Exception:
        pass

    # 4. botol
    await _safe_create_collection(db, "botol", validator=BOTOL)
    try:
        await db.botol.create_index(
            [("mesin_id", 1), ("waktu_keluar", -1)], name="mesin_waktu_keluar"
        )
        await db.botol.create_index(
            [("mesin_id", 1), ("sesi_id", 1)], name="mesin_sesi"
        )
        await db.botol.create_index(
            [("id_kirim", 1)],
            name="id_kirim_unik",
            unique=True,
            partialFilterExpression={"id_kirim": {"$type": "string"}},
        )
    except Exception:
        pass

    yield db

    mock_client.close()


@pytest.fixture
async def client(test_db, test_settings) -> AsyncGenerator[AsyncClient, None]:
    """HTTP Client berbasis httpx AsyncClient untuk menguji endpoint aplikasi."""
    old_client = db_instance.client
    old_db = db_instance.db

    db_instance.client = test_db.client
    db_instance.db = test_db

    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_db] = lambda: test_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    db_instance.client = old_client
    db_instance.db = old_db


@pytest.fixture
def auth_headers() -> dict:
    """Header autentikasi yang sah untuk pengujian."""
    return {"X-Api-Key": TEST_API_KEY}
