"""Main FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.db import close_db_connection, connect_to_db
from app.routers import baca, health, tulis

# Setup basic logging (tanpa mencatat isi body penuh atau API key)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager untuk mengelola koneksi MongoDB."""
    logger.info("Memulai aplikasi REST API Mesin Pengisi Botol...")
    await connect_to_db()
    yield
    logger.info("Menghentikan aplikasi...")
    await close_db_connection()


def _format_loc(loc: tuple) -> str:
    """Mengubah tuple lokasi error Pydantic menjadi format path yang mudah dibaca."""
    parts = [str(x) for x in loc if x != "body"]
    if not parts:
        return "body"

    formatted = ""
    for p in parts:
        if p.isdigit():
            formatted += f"[{p}]"
        else:
            if formatted and not formatted.endswith("]"):
                formatted += f".{p}"
            elif formatted and formatted.endswith("]"):
                formatted += f".{p}"
            else:
                formatted += p
    return formatted


def _translate_message(msg: str) -> str:
    """Merapikan pesan error ke dalam Bahasa Indonesia yang informatif."""
    if msg.startswith("Value error, "):
        msg = msg[len("Value error, "):]

    # Terjemahan umum pydantic v2
    if msg == "Field required":
        return "Field ini wajib diisi"
    if "Input should be a valid integer" in msg:
        return "Nilai harus berupa bilangan bulat (integer)"
    if "Input should be a valid number" in msg:
        return "Nilai harus berupa angka (number)"
    if "Input should be a valid boolean" in msg:
        return "Nilai harus berupa boolean (true atau false)"
    if "Input should be a valid string" in msg:
        return "Nilai harus berupa teks (string)"
    if "Input should be greater than or equal to" in msg:
        limit = msg.split()[-1]
        return f"Nilai harus lebih besar atau sama dengan {limit}"
    if "Input should be less than or equal to" in msg:
        limit = msg.split()[-1]
        return f"Nilai harus lebih kecil atau sama dengan {limit}"
    if "Input should be a valid list" in msg:
        return "Body harus berupa array / list data"
    if "Input should be 'Mati', 'Siap', 'Berjalan' or 'Darurat'" in msg:
        return "Nilai mode harus salah satu dari: Mati, Siap, Berjalan, Darurat"
    if "Input should be 'OK', 'TIDAK_PENUH' or 'TANPA_TUTUP'" in msg:
        return "Status botol harus salah satu dari: OK, TIDAK_PENUH, TANPA_TUTUP"
    if "Input should be 'pemain', 'sistem', 'operator' or 'esp32'" in msg:
        return "Sumber harus salah satu dari: pemain, sistem, operator, esp32"

    return msg


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Mengubah error validasi bawaan FastAPI (HTTP 422) menjadi HTTP 400 Bad Request
    dengan format daftar field yang salah dalam Bahasa Indonesia.
    """
    errors: List[Dict[str, str]] = []
    for err in exc.errors():
        field_path = _format_loc(err.get("loc", ()))
        message = _translate_message(err.get("msg", "Data tidak valid"))
        errors.append({
            "field": field_path,
            "pesan": message,
        })

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": "Validasi data gagal",
            "errors": errors,
        },
    )


def create_app(custom_settings: Optional[Settings] = None) -> FastAPI:
    """Factory function untuk inisialisasi aplikasi FastAPI dengan konfigurasi."""
    current_settings = custom_settings or get_settings()

    openapi_tags = [
        {
            "name": "Health",
            "description": "Pemeriksaan kesehatan server dan status konektivitas database MongoDB Atlas.",
        },
        {
            "name": "Tulis Data",
            "description": "Endpoint ingest data telemetri batch (1-10 data), event mesin, dan botol selesai dari Unity / ESP32 (Header X-Api-Key wajib).",
        },
        {
            "name": "Live Monitoring & Konfigurasi Mesin",
            "description": "Endpoint pembacaan status operasional real-time mesin, status MCB, sudut turret, GPIO, dan riwayat event.",
        },
        {
            "name": "Analitik MES & Laporan",
            "description": "Endpoint agregasi produksi, kualitas (OK vs gagal & kategori defect), downtime (E-stop), traceability botol, dan laporan terpadu.",
        },
    ]

    app_instance = FastAPI(
        title="MES Liquid Filling Machine Backend API",
        description=(
            "REST API perantara berperforma tinggi antara digital twin Unity dan MongoDB Atlas, "
            "serta backend analitik terpadu untuk Manufacturing Execution System (MES) Frontend. "
            "Mendukung Live Monitoring, Produksi, Kualitas, Downtime, Traceability, dan Laporan."
        ),
        version="1.2.0",
        openapi_tags=openapi_tags,
        lifespan=lifespan,
        debug=current_settings.DEBUG,
        servers=[{"url": current_settings.API_BASE_URL, "description": "API Base URL"}] if current_settings.API_BASE_URL else None,
    )

    # Konfigurasi CORS Middleware untuk integrasi Frontend MES
    # Mengizinkan origin yang terdaftar (tidak menggunakan wildcard '*' pada production)
    app_instance.add_middleware(
        CORSMiddleware,
        allow_origins=current_settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Registrasi exception handler validasi Pydantic
    app_instance.add_exception_handler(RequestValidationError, validation_exception_handler)

    # Registrasi router dengan prefix dinamis dari konfigurasi (default /api/v1)
    api_prefix = current_settings.API_V1_STR.rstrip("/")
    app_instance.include_router(health.router, prefix=api_prefix)
    app_instance.include_router(tulis.router, prefix=api_prefix)
    app_instance.include_router(baca.router, prefix=api_prefix)

    # Dukung juga prefix /api langsung untuk kemudahan akses dan integrasi Live Monitoring Frontend MES & Unity
    if api_prefix != "/api":
        app_instance.include_router(health.router, prefix="/api")
        app_instance.include_router(tulis.router, prefix="/api")
        app_instance.include_router(baca.router, prefix="/api")

    # Endpoint /health di root juga disediakan untuk kemudahan monitoring & docker healthcheck
    app_instance.include_router(health.router)

    return app_instance


settings = get_settings()
app = create_app(settings)
