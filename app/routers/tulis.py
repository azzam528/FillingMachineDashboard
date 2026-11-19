"""Router untuk endpoint tulis: telemetri, event, botol, batch (prefix /api)."""

from datetime import datetime, timezone
from typing import List, Union
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth import verify_mesin_exists, verify_write_api_key
from app.config import Settings, get_settings
from app.db import get_db
from app.kpi import evaluate_batch_kpis
from app.models import (
    BatchCreate,
    BotolCreate,
    EventCreate,
    TelemetriCreate,
    TelemetriResponse,
    WriteSingleResponse,
)

router = APIRouter(tags=["Tulis Data"], dependencies=[Depends(verify_write_api_key)])


async def _simpan_single(collection, item: Union[EventCreate, BotolCreate], nama: str) -> WriteSingleResponse:
    """Helper sederhana untuk menyimpan dokumen tunggal dengan idempotensi id_kirim."""
    doc = item.model_dump()
    doc["diterima"] = datetime.now(timezone.utc)
    try:
        res = await collection.insert_one(doc)
        return WriteSingleResponse(
            status="sukses",
            pesan=f"{nama} berhasil disimpan",
            id_kirim=item.id_kirim,
            tersimpan=True,
            id=str(res.inserted_id),
        )
    except DuplicateKeyError:
        return WriteSingleResponse(
            status="sukses",
            pesan="duplikat diabaikan",
            id_kirim=item.id_kirim,
            tersimpan=False,
            id=None,
        )


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
            if doc.get("id_kirim"):
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
    return await _simpan_single(db.event, event, "event")


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
    """Menerima dan menyimpan 1 dokumen botol saat botol keluar stasiun QC / jatuh ke kotak.

    - Wajib membawa header X-Api-Key yang valid.
    - mesin_id divalidasi ke collection 'mesin' -> jika tidak ada -> 400.
    - Perhitungan otomatis durasi_isi_detik dan unit_mlt_detik jika tidak dikirim.
    - Validasi urutan waktu menaik (waktu_masuk <= isi <= tutup <= keluar).
    - Idempotent: jika id_kirim sudah ada (DuplicateKeyError), tangkap dan balas 201 'duplikat diabaikan'.
    """
    await verify_mesin_exists(botol.mesin_id, db=db)
    return await _simpan_single(db.botol, botol, "botol")


@router.post(
    "/batch",
    status_code=status.HTTP_201_CREATED,
    response_model=WriteSingleResponse,
    summary="Simpan 1 dokumen batch produksi selesai",
)
async def simpan_batch(
    batch: BatchCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Menerima dan menyimpan ringkasan batch produksi setelah satu batch selesai dikemas.

    - Wajib membawa header X-Api-Key yang valid.
    - mesin_id divalidasi ke collection 'mesin' -> jika tidak ada -> 400.
    - Menghitung ulang KPI batch (Production Time, Availability, Performance, Quality, OEE, Cycle Time).
    - Menyimpan nilai Unity (*_unity) dan nilai hasil kalkulasi server.
    - Mengevaluasi kpi_mismatch (true jika selisih nilai > KPI_MISMATCH_TOLERANCE / 0.5 poin persen).
    - Idempoten: DuplicateKeyError pada id_kirim atau compound key (sesi_id, batch_ke) ditangani dengan sukses 'duplikat diabaikan'.
    """
    await verify_mesin_exists(batch.mesin_id, db=db)

    # Evaluasi ulang metrik KPI
    evaluated = evaluate_batch_kpis(
        planned_production_time=batch.planned_production_time,
        downtime_unplanned=batch.downtime_unplanned or 0.0,
        setup_time=batch.setup_time or 0.0,
        starvation_downtime=batch.starvation_downtime or 0.0,
        packaging_time=batch.packaging_time or 0.0,
        botol_selesai=batch.botol_selesai,
        botol_ok=batch.botol_ok,
        ideal_cycle_time=batch.ideal_cycle_time or settings.IDEAL_CYCLE_TIME,
        mlt_batch=batch.mlt_batch,
        tolerance_pct=settings.KPI_MISMATCH_TOLERANCE,
        unity_availability_pct=batch.availability_pct,
        unity_performance_pct=batch.performance_pct,
        unity_quality_pct=batch.quality_pct,
        unity_oee_pct=batch.oee_pct,
    )

    doc = batch.model_dump()
    doc["diterima"] = datetime.now(timezone.utc)

    # Arsipkan metrik kiriman Unity jika disediakan
    if batch.availability_pct is not None:
        doc["availability_pct_unity"] = batch.availability_pct
    if batch.performance_pct is not None:
        doc["performance_pct_unity"] = batch.performance_pct
    if batch.quality_pct is not None:
        doc["quality_pct_unity"] = batch.quality_pct
    if batch.oee_pct is not None:
        doc["oee_pct_unity"] = batch.oee_pct

    # Timpa dengan nilai hasil verifikasi / perhitungan server
    doc["production_time"] = evaluated["production_time"]
    doc["availability_pct"] = evaluated["availability_pct"]
    doc["performance_pct"] = evaluated["performance_pct"]
    doc["quality_pct"] = evaluated["quality_pct"]
    doc["oee_pct"] = evaluated["oee_pct"]
    doc["actual_cycle_time_avg"] = evaluated["actual_cycle_time_avg"]
    doc["effective_capacity_per_hour"] = evaluated["effective_capacity_per_hour"]
    doc["kpi_mismatch"] = evaluated["kpi_mismatch"]

    try:
        res = await db.batch.insert_one(doc)
        return WriteSingleResponse(
            status="sukses",
            pesan="batch berhasil disimpan",
            id_kirim=batch.id_kirim,
            tersimpan=True,
            id=str(res.inserted_id),
        )
    except DuplicateKeyError:
        return WriteSingleResponse(
            status="sukses",
            pesan="duplikat diabaikan",
            id_kirim=batch.id_kirim,
            tersimpan=False,
            id=None,
        )
