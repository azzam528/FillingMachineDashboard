"""Router untuk endpoint baca: status mesin, telemetri, event, ringkasan (prefix /api/v1)."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import verify_read_access
from app.config import Settings, get_settings
from app.db import get_db
from app.models import RingkasanResponse, parse_iso8601_utc

router = APIRouter(prefix="/mesin", tags=["Baca Data"])


def _serialize_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Helper untuk mengonversi ObjectId MongoDB ke string dan memastikan serialisasi aman."""
    if not doc:
        return None
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


@router.get(
    "/{id}",
    summary="Ambil konfigurasi mesin berdasarkan ID",
)
async def ambil_konfigurasi_mesin(
    id: str,
    _: Optional[str] = Depends(verify_read_access),
):
    """Membaca data konfigurasi mesin dari collection 'mesin'."""
    db = get_db()
    doc = await db.mesin.find_one({"_id": id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mesin dengan id '{id}' tidak ditemukan",
        )
    return _serialize_doc(doc)


@router.get(
    "/{id}/status",
    summary="Ambil telemetri status terakhir mesin",
)
async def ambil_status_terakhir(
    id: str,
    _: Optional[str] = Depends(verify_read_access),
):
    """Membaca 1 data telemetri terakhir (sort waktu descending)."""
    db = get_db()
    doc = await db.telemetri.find_one(
        {"mesin_id": id},
        sort=[("waktu", -1)],
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data telemetri untuk mesin '{id}' belum tersedia",
        )
    return _serialize_doc(doc)


@router.get(
    "/{id}/ringkasan",
    response_model=RingkasanResponse,
    summary="Ambil ringkasan produksi mesin",
)
async def ambil_ringkasan_produksi(
    id: str,
    dari: Optional[str] = Query(None, description="Awal rentang waktu (ISO 8601 UTC)"),
    sampai: Optional[str] = Query(None, description="Akhir rentang waktu (ISO 8601 UTC)"),
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan sesi_id tertentu"),
    _: Optional[str] = Depends(verify_read_access),
    settings: Settings = Depends(get_settings),
):
    db = get_db()

    # Parse rentang waktu jika ada
    dt_dari: Optional[datetime] = None
    dt_sampai: Optional[datetime] = None

    try:
        if dari:
            dt_dari = parse_iso8601_utc(dari)
        if sampai:
            dt_sampai = parse_iso8601_utc(sampai)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Parameter filter waktu tidak valid: {str(e)}",
        )

    if dt_dari and dt_sampai and dt_dari > dt_sampai:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parameter 'dari' tidak boleh lebih besar dari 'sampai'",
        )

    # 1. Agregasi data botol (jumlah, gagal, rata-rata waktu siklus)
    match_botol: Dict[str, Any] = {"mesin_id": id}
    if sesi_id:
        match_botol["sesi_id"] = sesi_id

    if dt_dari or dt_sampai:
        time_filter: Dict[str, Any] = {}
        if dt_dari:
            time_filter["$gte"] = dt_dari
        if dt_sampai:
            time_filter["$lte"] = dt_sampai
        match_botol["waktu_keluar"] = time_filter

    pipeline_botol = [
        {"$match": match_botol},
        {
            "$group": {
                "_id": None,
                "total_botol": {"$sum": 1},
                "botol_gagal": {
                    "$sum": {
                        "$cond": [{"$ne": ["$status", "OK"]}, 1, 0]
                    }
                },
                "rata_rata_siklus": {
                    "$avg": {
                        "$divide": [
                            {"$subtract": ["$waktu_keluar", "$waktu_masuk"]},
                            1000.0,
                        ]
                    }
                },
            }
        },
    ]

    cursor_botol = db.botol.aggregate(pipeline_botol)
    botol_stats = await cursor_botol.to_list(length=1)

    jumlah_botol = 0
    botol_gagal = 0
    rata_rata_siklus = 0.0

    if botol_stats:
        jumlah_botol = int(botol_stats[0].get("total_botol", 0))
        botol_gagal = int(botol_stats[0].get("botol_gagal", 0))
        raw_avg = botol_stats[0].get("rata_rata_siklus")
        rata_rata_siklus = round(float(raw_avg), 3) if raw_avg is not None else 0.0

    # 2. Hitung total durasi Darurat (E-stop)
    # Memasangkan event 'estop_tekan' dan 'estop_lepas' per sesi_id
    estop_tekan_jenis = settings.EVENT_JENIS_ESTOP_TEKAN
    estop_lepas_jenis = settings.EVENT_JENIS_ESTOP_LEPAS

    match_event: Dict[str, Any] = {
        "mesin_id": id,
        "jenis": {"$in": [estop_tekan_jenis, estop_lepas_jenis]},
    }
    if sesi_id:
        match_event["sesi_id"] = sesi_id

    # Ambil event darurat urut berdasarkan sesi_id dan waktu kronologis
    cursor_event = db.event.find(match_event).sort([("sesi_id", 1), ("waktu", 1)])
    events = await cursor_event.to_list(length=None)

    total_durasi_darurat = 0.0
    now_utc = datetime.now(timezone.utc)

    # Kelompokkan event per sesi_id
    sesi_events: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        s_id = ev.get("sesi_id", "")
        sesi_events.setdefault(s_id, []).append(ev)

    for s_id, ev_list in sesi_events.items():
        active_tekan_waktu: Optional[datetime] = None

        for ev in ev_list:
            ev_waktu = ev["waktu"]
            # Pastikan ev_waktu tz-aware UTC
            if ev_waktu.tzinfo is None:
                ev_waktu = ev_waktu.replace(tzinfo=timezone.utc)

            jenis = ev.get("jenis")
            if jenis == estop_tekan_jenis:
                if active_tekan_waktu is None:
                    active_tekan_waktu = ev_waktu
            elif jenis == estop_lepas_jenis:
                if active_tekan_waktu is not None:
                    t_start = active_tekan_waktu
                    t_end = ev_waktu

                    # Potong (clip) sesuai rentang [dari, sampai] jika diminta
                    start_effective = max(t_start, dt_dari) if dt_dari else t_start
                    end_effective = min(t_end, dt_sampai) if dt_sampai else t_end

                    if end_effective > start_effective:
                        total_durasi_darurat += (end_effective - start_effective).total_seconds()

                    active_tekan_waktu = None

        # Jika masih dalam kondisi ditekan tanpa dilepas
        if active_tekan_waktu is not None:
            t_start = active_tekan_waktu
            t_end = dt_sampai if dt_sampai else now_utc

            start_effective = max(t_start, dt_dari) if dt_dari else t_start
            end_effective = min(t_end, dt_sampai) if dt_sampai else t_end

            if end_effective > start_effective:
                total_durasi_darurat += (end_effective - start_effective).total_seconds()

    return RingkasanResponse(
        mesin_id=id,
        sesi_id=sesi_id,
        rentang={
            "dari": dt_dari.isoformat() if dt_dari else None,
            "sampai": dt_sampai.isoformat() if dt_sampai else None,
        },
        jumlah_botol=jumlah_botol,
        botol_gagal=botol_gagal,
        rata_rata_waktu_siklus_detik=rata_rata_siklus,
        total_durasi_darurat_detik=round(total_durasi_darurat, 3),
    )


@router.get(
    "/{id}/event",
    summary="Ambil riwayat event mesin",
)
async def ambil_riwayat_event(
    id: str,
    jenis: Optional[str] = Query(None, description="Filter nama jenis event"),
    dari: Optional[str] = Query(None, description="Awal rentang waktu (ISO 8601 UTC)"),
    sampai: Optional[str] = Query(None, description="Akhir rentang waktu (ISO 8601 UTC)"),
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan sesi_id"),
    limit: int = Query(100, ge=1, le=1000, description="Jumlah data maksimal (1–1000, default 100)"),
    _: Optional[str] = Depends(verify_read_access),
):
    """Membaca daftar event mesin, terurut dari yang terbaru (waktu desc)."""
    db = get_db()
    query: Dict[str, Any] = {"mesin_id": id}

    if jenis:
        query["jenis"] = jenis
    if sesi_id:
        query["sesi_id"] = sesi_id

    try:
        dt_dari = parse_iso8601_utc(dari) if dari else None
        dt_sampai = parse_iso8601_utc(sampai) if sampai else None
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Parameter filter waktu tidak valid: {str(e)}",
        )

    if dt_dari or dt_sampai:
        time_filter: Dict[str, Any] = {}
        if dt_dari:
            time_filter["$gte"] = dt_dari
        if dt_sampai:
            time_filter["$lte"] = dt_sampai
        query["waktu"] = time_filter

    cursor = db.event.find(query).sort("waktu", -1).limit(limit)
    events = []
    async for doc in cursor:
        events.append(_serialize_doc(doc))

    return events
