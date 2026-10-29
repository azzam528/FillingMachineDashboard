"""Koneksi database MongoDB menggunakan Motor (async driver)."""

import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import get_settings

logger = logging.getLogger("app.db")

class Database:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None

db_instance = Database()


async def connect_to_db() -> None:
    """Inisialisasi client MongoDB saat startup aplikasi."""
    settings = get_settings()
    logger.info("Menghubungkan ke MongoDB Atlas (nama database: %s)...", settings.MONGODB_DB_NAME)
    
    # Catatan keamanan: MONGODB_URI tidak dicetak ke log
    db_instance.client = AsyncIOMotorClient(
        settings.MONGODB_URI,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
    )
    db_instance.db = db_instance.client[settings.MONGODB_DB_NAME]
    
    # Verifikasi koneksi sekali saat startup
    try:
        await db_instance.client.admin.command("ping")
        logger.info("Berhasil terhubung ke MongoDB Atlas.")
    except Exception as e:
        logger.warning("Gagal melakukan ping ke MongoDB saat startup: %s", str(e))


async def close_db_connection() -> None:
    """Tutup koneksi MongoDB saat shutdown aplikasi."""
    if db_instance.client is not None:
        logger.info("Menutup koneksi MongoDB...")
        db_instance.client.close()
        db_instance.client = None
        db_instance.db = None
        logger.info("Koneksi MongoDB ditutup.")


def get_db() -> AsyncIOMotorDatabase:
    """Mendapatkan instance database aktif."""
    if db_instance.db is None:
        raise RuntimeError("Database belum diinisialisasi atau koneksi belum dibuka.")
    return db_instance.db


def get_client() -> AsyncIOMotorClient:
    """Mendapatkan client MongoDB aktif."""
    if db_instance.client is None:
        raise RuntimeError("Client MongoDB belum diinisialisasi.")
    return db_instance.client
