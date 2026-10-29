"""Modul autentikasi dan otorisasi menggunakan API Key per mesin."""

import secrets
from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from app.config import Settings, get_settings


def get_authenticated_mesin_id(
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
    settings: Settings = Depends(get_settings),
) -> str:
    """Memvalidasi header X-Api-Key terhadap daftar kunci per mesin.
    
    Mengembalikan mesin_id pemilik kunci jika valid.
    Mengangkat HTTP 401 jika kunci tidak ada atau salah.
    Menggunakan secrets.compare_digest untuk mencegah timing attacks.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header X-Api-Key wajib disertakan",
        )

    api_keys_map = settings.mesin_api_keys_map

    matched_mesin_id: Optional[str] = None
    # Iterasi semua kunci terdaftar dan bandingkan dengan compare_digest
    for mesin_id, expected_key in api_keys_map.items():
        if secrets.compare_digest(x_api_key, expected_key):
            matched_mesin_id = mesin_id
            break

    if matched_mesin_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key tidak valid atau tidak terdaftar",
        )

    return matched_mesin_id


def verify_mesin_access(authenticated_mesin_id: str, target_mesin_id: str) -> None:
    """Memverifikasi bahwa mesin_id pada body/target sesuai dengan pemilik API Key.
    
    Jika berbeda, mengangkat HTTP 403 Forbidden.
    """
    if authenticated_mesin_id != target_mesin_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Akses ditolak: API Key milik mesin '{authenticated_mesin_id}' "
                f"tidak diizinkan mengakses data mesin '{target_mesin_id}'"
            ),
        )


def verify_read_access(
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
    settings: Settings = Depends(get_settings),
) -> Optional[str]:
    """Dependency untuk endpoint baca.
    
    Jika REQUIRE_KEY_FOR_READ bernilai True, header X-Api-Key wajib valid.
    Jika bernilai False, endpoint dapat diakses secara publik (mengembalikan mesin_id jika ada).
    """
    if settings.REQUIRE_KEY_FOR_READ:
        return get_authenticated_mesin_id(x_api_key, settings=settings)
    
    # Jika key tidak wajib tapi dikirimkan, tetap lakukan validasi jika ada
    if x_api_key is not None:
        for mesin_id, expected_key in settings.mesin_api_keys_map.items():
            if secrets.compare_digest(x_api_key, expected_key):
                return mesin_id
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key tidak valid",
        )
    return None
