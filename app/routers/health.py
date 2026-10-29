"""Router untuk endpoint health check (GET /health dan GET /api/v1/health)."""

from datetime import datetime, timezone
from fastapi import APIRouter, Response, status

from app.db import db_instance
from app.models import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Cek status API dan koneksi database",
)
async def health_check(response: Response):
    """Memeriksa kesehatan layanan REST API dan konektivitas ke database MongoDB Atlas."""
    now_iso = datetime.now(timezone.utc).isoformat()

    if db_instance.client is None or db_instance.db is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="error",
            database="terputus",
            waktu=now_iso,
            detail="Client database belum diinisialisasi",
        )

    try:
        await db_instance.client.admin.command("ping")
        return HealthResponse(
            status="ok",
            database="terhubung",
            waktu=now_iso,
            detail=None,
        )
    except Exception as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="error",
            database="terputus",
            waktu=now_iso,
            detail=str(e),
        )

