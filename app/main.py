"""Main FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
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


settings = get_settings()

app = FastAPI(
    title="Liquid Filling Machine REST API",
    description=(
        "REST API perantara antara digital twin Unity dan MongoDB Atlas "
        "untuk sistem pencatatan data mesin pengisi botol rotary 10 slot."
    ),
    version="1.0.0",
    lifespan=lifespan,
    debug=settings.DEBUG,
)


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


@app.exception_handler(RequestValidationError)
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


# Registrasi router dengan prefix /api/v1
app.include_router(health.router, prefix="/api/v1")
app.include_router(tulis.router, prefix="/api/v1")
app.include_router(baca.router, prefix="/api/v1")

# Endpoint /health di root juga disediakan untuk kemudahan monitoring & docker healthcheck
app.include_router(health.router)
