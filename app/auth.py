"""Modul autentikasi dan validasi otorisasi."""

import secrets
from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import Settings, get_settings
from app.db import get_db


def verify_write_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
    settings: Settings = Depends(get_settings),
) -> str:
    """Memvalidasi header X-Api-Key untuk endpoint tulis.

    Kunci dibaca dari env API_KEY (satu kunci untuk semua pengirim).
    Bandingkan dengan secrets.compare_digest.
    Key salah atau tidak ada -> 401 Unauthorized.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header X-Api-Key wajib disertakan",
        )

    if not secrets.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key tidak valid",
        )

    return x_api_key


async def verify_mesin_exists(
    mesin_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> None:
    """Memvalidasi bahwa mesin_id ada di collection 'mesin'.

    Jika tidak ditemukan di database, raise HTTP 400 Bad Request.
    """
    if not mesin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'mesin_id' wajib diisi",
        )

    doc = await db.mesin.find_one({"_id": mesin_id}, {"_id": 1})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mesin dengan id '{mesin_id}' tidak terdaftar di sistem",
        )


def verify_read_access(
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
    settings: Settings = Depends(get_settings),
) -> Optional[str]:
    """Dependency untuk endpoint baca.

    Jika REQUIRE_KEY_FOR_READ bernilai True, header X-Api-Key wajib valid.
    Jika bernilai False, endpoint dapat diakses secara terbuka.
    """
    if settings.REQUIRE_KEY_FOR_READ:
        if not x_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Header X-Api-Key wajib disertakan",
            )
        if not secrets.compare_digest(x_api_key, settings.API_KEY):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key tidak valid",
            )
        return x_api_key

    return None
