"""Router untuk endpoint tulis: telemetri, event, botol (prefix /api/v1)."""

from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth import verify_mesin_exists, verify_write_api_key
from app.db import get_db
from app.models import (
    BotolCreate,
    EventCreate,
    TelemetriCreate,
    TelemetriResponse,
    WriteSingleResponse,
)

router = APIRouter(tags=["Tulis Data"], dependencies=[Depends(verify_write_api_key)])


@router.post(
    "/telemetri",
    status_code=status.HTTP_201_CREATED,
    response_model=TelemetriResponse,
    summary="Simpan 1–10 dokumen telemetri",
)
async def simpan_telemetri(
    items: List[TelemetriCreate],
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Menerima 1–10 dokumen telemetri (batch).

    - Batas batch: 1 sampai 10 dokumen per request. Lebih dari 10 atau kosong -> 400 Bad Request.
    - Validasi mesin_id terdaftar di collection 'mesin' -> jika tidak -> 400.
    - Dedup id_kirim: dokumen yang id_kirim-nya sudah tercatat akan dilewati.
    - Menambahkan timestamp server 'diterima' (UTC) pada setiap dokumen.
    """
    if len(items) < 1 or len(items) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Jumlah dokumen telemetri harus antara 1 sampai 10 dokumen per permintaan",
        )

    # Validasi bahwa semua mesin_id terdaftar di database
    unique_mesin_ids = {item.mesin_id for item in items}
    for mid in unique_mesin_ids:
        await verify_mesin_exists(mid, db=db)

    server_now = datetime.now(timezone.utc)

    # Siapkan dokumen
    docs_to_process = []
    id_kirim_list = []
    for item in items:
        d = item.model_dump()
        d["diterima"] = server_now
        docs_to_process.append(d)
        if d.get("id_kirim"):
            id_kirim_list.append(d["id_kirim"])

    # Dedup id_kirim di API karena time series collection tidak mendukung unique index
    existing_id_kirim = set()
    if id_kirim_list:
        cursor = db.telemetri.find(
            {"mesin_id": {"$in": list(unique_mesin_ids)}, "id_kirim": {"$in": id_kirim_list}},
            {"id_kirim": 1},
        )
        async for doc in cursor:
            if "id_kirim" in doc and doc["id_kirim"]:
                existing_id_kirim.add(doc["id_kirim"])

    # Filter dokumen yang belum ada id_kirim-nya
    docs_to_insert = [
        d for d in docs_to_process
        if not d.get("id_kirim") or d["id_kirim"] not in existing_id_kirim
    ]
    duplikat_count = len(docs_to_process) - len(docs_to_insert)

    if docs_to_insert:
        await db.telemetri.insert_many(docs_to_insert)

    return TelemetriResponse(
        status="sukses",
        pesan=f"{len(docs_to_insert)} data tersimpan, {duplikat_count} duplikat diabaikan",
        tersimpan=len(docs_to_insert),
        duplikat_diabaikan=duplikat_count,
    )


@router.post(
    "/event",
    status_code=status.HTTP_201_CREATED,
    response_model=WriteSingleResponse,
    summary="Simpan 1 dokumen event",
)
async def simpan_event(
    event: EventCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Menerima dan menyimpan 1 dokumen kejadian (event).

    - Wajib membawa header X-Api-Key yang valid.
    - mesin_id divalidasi ke collection 'mesin' -> jika tidak ada -> 400.
    - Idempotent: jika id_kirim sudah ada (DuplicateKeyError), tangkap dan balas 201 'duplikat diabaikan'.
    """
    await verify_mesin_exists(event.mesin_id, db=db)

    server_now = datetime.now(timezone.utc)
    doc = event.model_dump()
    doc["diterima"] = server_now

    try:
        result = await db.event.insert_one(doc)
        return WriteSingleResponse(
            status="sukses",
            pesan="event berhasil disimpan",
            id_kirim=event.id_kirim,
            tersimpan=True,
            id=str(result.inserted_id),
        )
    except DuplicateKeyError:
        # Idempotent response saat id_kirim sudah ada
        return WriteSingleResponse(
            status="sukses",
            pesan="duplikat diabaikan",
            id_kirim=event.id_kirim,
            tersimpan=False,
            id=None,
        )


@router.post(
    "/botol",
    status_code=status.HTTP_201_CREATED,
    response_model=WriteSingleResponse,
    summary="Simpan 1 dokumen data botol",
)
async def simpan_botol(
    botol: BotolCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Menerima dan menyimpan 1 dokumen botol saat botol masuk kotak penampung.

    - Wajib membawa header X-Api-Key yang valid.
    - mesin_id divalidasi ke collection 'mesin' -> jika tidak ada -> 400.
    - Idempotent: jika id_kirim sudah ada (DuplicateKeyError), tangkap dan balas 201 'duplikat diabaikan'.
    """
    await verify_mesin_exists(botol.mesin_id, db=db)

    server_now = datetime.now(timezone.utc)
    doc = botol.model_dump()
    doc["diterima"] = server_now

    try:
        result = await db.botol.insert_one(doc)
        return WriteSingleResponse(
            status="sukses",
            pesan="botol berhasil disimpan",
            id_kirim=botol.id_kirim,
            tersimpan=True,
            id=str(result.inserted_id),
        )
    except DuplicateKeyError:
        # Idempotent response saat id_kirim sudah ada
        return WriteSingleResponse(
            status="sukses",
            pesan="duplikat diabaikan",
            id_kirim=botol.id_kirim,
            tersimpan=False,
            id=None,
        )
