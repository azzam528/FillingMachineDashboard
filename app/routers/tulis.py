"""Router untuk endpoint tulis: telemetri, event, botol (prefix /api/v1)."""

from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.auth import get_authenticated_mesin_id, verify_mesin_access
from app.db import get_db
from app.models import (
    BotolCreate,
    EventCreate,
    TelemetriCreate,
    TelemetriResponse,
    WriteSingleResponse,
)

router = APIRouter(tags=["Tulis Data"])


@router.post(
    "/telemetri",
    status_code=status.HTTP_201_CREATED,
    response_model=TelemetriResponse,
    summary="Simpan 1–10 dokumen telemetri",
)
async def simpan_telemetri(
    items: List[TelemetriCreate],
    auth_mesin_id: str = Depends(get_authenticated_mesin_id),
):
    """Menerima 1–10 dokumen telemetri (batch).
    
    - Lebih dari 10 dokumen atau kosong -> 400 Bad Request.
    - Setiap dokumen divalidasi mesin_id harus sama dengan pemilik API key.
    - Dedup id_kirim: dokumen yang id_kirim-nya sudah tercatat akan dilewati.
    - Menambahkan timestamp server 'diterima' pada setiap dokumen.
    """
    if len(items) < 1 or len(items) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Jumlah dokumen telemetri harus antara 1 sampai 10 dokumen per permintaan",
        )

    # Validasi kepemilikan mesin untuk setiap item
    for item in items:
        verify_mesin_access(auth_mesin_id, item.mesin_id)

    db = get_db()
    server_now = datetime.now(timezone.utc)

    # Siapkan dokumen dalam bentuk dictionary
    docs_to_process = []
    id_kirim_list = []
    for item in items:
        d = item.model_dump()
        d["diterima"] = server_now
        docs_to_process.append(d)
        if d.get("id_kirim"):
            id_kirim_list.append(d["id_kirim"])

    # Dedup id_kirim untuk collection time series
    existing_id_kirim = set()
    if id_kirim_list:
        cursor = db.telemetri.find(
            {"mesin_id": auth_mesin_id, "id_kirim": {"$in": id_kirim_list}},
            {"id_kirim": 1},
        )
        async for doc in cursor:
            if "id_kirim" in doc:
                existing_id_kirim.add(doc["id_kirim"])

    # Filter hanya dokumen yang belum ada id_kirim-nya
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
    auth_mesin_id: str = Depends(get_authenticated_mesin_id),
):
    """Menerima dan menyimpan 1 dokumen kejadian (event).
    
    - Wajib membawa header X-Api-Key yang valid.
    - mesin_id harus cocok dengan API key.
    - Idempotent: jika id_kirim sudah ada (DuplicateKeyError), kembalikan 201 dengan pesan 'duplikat diabaikan'.
    """
    verify_mesin_access(auth_mesin_id, event.mesin_id)

    db = get_db()
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
        # Idempotent response
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
    auth_mesin_id: str = Depends(get_authenticated_mesin_id),
):
    """Menerima dan menyimpan 1 dokumen botol saat botol masuk kotak.
    
    - Wajib membawa header X-Api-Key yang valid.
    - mesin_id harus cocok dengan API key.
    - Idempotent: jika id_kirim sudah ada (DuplicateKeyError), kembalikan 201 dengan pesan 'duplikat diabaikan'.
    """
    verify_mesin_access(auth_mesin_id, botol.mesin_id)

    db = get_db()
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
        # Idempotent response
        return WriteSingleResponse(
            status="sukses",
            pesan="duplikat diabaikan",
            id_kirim=botol.id_kirim,
            tersimpan=False,
            id=None,
        )
