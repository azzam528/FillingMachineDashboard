"""Router untuk endpoint baca: status mesin, telemetri, event, ringkasan (prefix /api/v1 dan /api)."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.auth import verify_read_access
from app.config import Settings, get_settings
from app.db import get_db
from app.models import (
    RingkasanResponse,
    RingkasanStatistik,
    parse_iso8601_utc,
)

router = APIRouter(prefix="/mesin", tags=["Baca Data & Live Monitoring"])


def _serialize_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Helper rekursif untuk mengonversi BSON types (ObjectId, datetime) ke format JSON standar."""
    if doc is None:
        return None

    result = {}
    for key, value in doc.items():
        if key == "_id":
            result[key] = str(value)
        elif isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            iso_str = value.isoformat()
            if iso_str.endswith("+00:00"):
                iso_str = iso_str[:-6] + "Z"
            result[key] = iso_str
        elif isinstance(value, dict):
            result[key] = _serialize_doc(value)
        elif isinstance(value, list):
            result[key] = [
                _serialize_doc(item) if isinstance(item, dict)
                else (
                    (item.replace(tzinfo=timezone.utc).isoformat()[:-6] + "Z"
                     if item.tzinfo is None or item.tzinfo.utcoffset(item).total_seconds() == 0
                     else item.isoformat())
                    if isinstance(item, datetime)
                    else item
                )
                for item in value
            ]
        else:
            result[key] = value
    return result


@router.get(
    "",
    summary="Ambil seluruh daftar mesin yang terdaftar",
)
async def daftar_mesin(
    _: Optional[str] = Depends(verify_read_access),
):
    """Membaca seluruh dokumen mesin dari collection 'mesin'."""
    db = get_db()
    cursor = db.mesin.find().sort("_id", 1)
    mesin_list = []
    async for doc in cursor:
        mesin_list.append(_serialize_doc(doc))
    return mesin_list


@router.get(
    "/{id}",
    summary="Ambil konfigurasi mesin berdasarkan ID",
)
async def ambil_konfigurasi_mesin(
    id: str,
    _: Optional[str] = Depends(verify_read_access),
):
    """Membaca data konfigurasi fisik mesin dari collection 'mesin'."""
    db = get_db()
    clean_id = id.strip()
    doc = await db.mesin.find_one({"_id": clean_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mesin dengan id '{id}' tidak ditemukan",
        )
    return _serialize_doc(doc)


@router.get(
    "/{id}/status",
    summary="Ambil telemetri status terakhir mesin untuk Live Monitoring",
)
async def ambil_status_terakhir(
    id: str,
    pengguna: Optional[str] = Query(None, description="Filter telemetri berdasarkan nama pengguna"),
    sesi_id: Optional[str] = Query(None, description="Filter telemetri berdasarkan ID sesi"),
    _: Optional[str] = Depends(verify_read_access),
):
    """Membaca 1 data telemetri terakhir mesin (sort waktu descending).

    Menyediakan data live monitoring terkini mencakup:
    - mode mesin (Mati, Siap, Berjalan, Darurat)
    - status darurat (E-stop)
    - status sakelar MCB (utama, mesin, kontrol, lampu)
    - sudut putaran turret (derajat)
    - jumlah botol selesai, isi kotak, sisa peti
    - status sinyal 8 pin GPIO
    - tahap dan langkah proses berjalan
    """
    db = get_db()
    clean_id = id.strip()
    query: Dict[str, Any] = {"mesin_id": clean_id}

    if pengguna:
        query["pengguna"] = pengguna.strip().lower()
    if sesi_id:
        query["sesi_id"] = sesi_id.strip()

    # Query dokumen telemetri terbaru berdasarkan timestamp waktu pengirim
    doc = await db.telemetri.find_one(
        query,
        sort=[("waktu", -1), ("_id", -1)],
    )
    if not doc:
        detail_msg = f"Data telemetri untuk mesin '{id}' belum tersedia"
        if sesi_id and pengguna:
            detail_msg += f" untuk sesi '{sesi_id}' dan pengguna '{pengguna}'"
        elif sesi_id:
            detail_msg += f" untuk sesi '{sesi_id}'"
        elif pengguna:
            detail_msg += f" untuk pengguna '{pengguna}'"
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail_msg,
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
    pengguna: Optional[str] = Query(None, description="Filter berdasarkan pengguna"),
    _: Optional[str] = Depends(verify_read_access),
    settings: Settings = Depends(get_settings),
):
    """Menghitung ringkasan produksi:

    - Jumlah botol, botol gagal (status != 'OK'), rata-rata waktu siklus (detik).
    - Total durasi Darurat (E-stop) berpasangan (estop_tekan & estop_lepas).
    - Filter opsional: dari, sampai, sesi_id, pengguna.
    - Menampilkan rincian per pengguna jika filter pengguna tidak diberikan.
    """
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

    norm_pengguna = pengguna.strip().lower() if pengguna else None

    # =========================================================================
    # 1. Agregasi Data Botol
    # =========================================================================
    match_botol: Dict[str, Any] = {"mesin_id": id}
    if sesi_id:
        match_botol["sesi_id"] = sesi_id
    if norm_pengguna:
        match_botol["pengguna"] = norm_pengguna

    if dt_dari or dt_sampai:
        time_filter: Dict[str, Any] = {}
        if dt_dari:
            time_filter["$gte"] = dt_dari
        if dt_sampai:
            time_filter["$lte"] = dt_sampai
        match_botol["waktu_keluar"] = time_filter

    user_botol_stats: Dict[str, Dict[str, Any]] = {}
    overall_total_botol = 0
    overall_botol_gagal = 0
    overall_cycle_sum = 0.0

    if norm_pengguna:
        # Query untuk pengguna tunggal
        pipeline_single = [
            {"$match": match_botol},
            {
                "$group": {
                    "_id": None,
                    "total_botol": {"$sum": 1},
                    "botol_gagal": {
                        "$sum": {"$cond": [{"$ne": ["$status", "OK"]}, 1, 0]}
                    },
                    "total_siklus_detik": {
                        "$sum": {
                            "$divide": [
                                {"$subtract": ["$waktu_keluar", "$waktu_masuk"]},
                                1000.0,
                            ]
                        }
                    },
                }
            },
        ]
        res = await db.botol.aggregate(pipeline_single).to_list(1)
        if res:
            overall_total_botol = int(res[0].get("total_botol", 0))
            overall_botol_gagal = int(res[0].get("botol_gagal", 0))
            overall_cycle_sum = float(res[0].get("total_siklus_detik", 0.0))
    else:
        # Group by pengguna untuk menyajikan rincian per pengguna
        pipeline_per_user = [
            {"$match": match_botol},
            {
                "$group": {
                    "_id": "$pengguna",
                    "total_botol": {"$sum": 1},
                    "botol_gagal": {
                        "$sum": {"$cond": [{"$ne": ["$status", "OK"]}, 1, 0]}
                    },
                    "total_siklus_detik": {
                        "$sum": {
                            "$divide": [
                                {"$subtract": ["$waktu_keluar", "$waktu_masuk"]},
                                1000.0,
                            ]
                        }
                    },
                }
            },
        ]
        user_rows = await db.botol.aggregate(pipeline_per_user).to_list(100)
        for row in user_rows:
            u = row.get("_id") or "unknown"
            t_botol = int(row.get("total_botol", 0))
            b_gagal = int(row.get("botol_gagal", 0))
            c_sum = float(row.get("total_siklus_detik", 0.0))
            user_botol_stats[u] = {
                "total_botol": t_botol,
                "botol_gagal": b_gagal,
                "total_siklus_detik": c_sum,
                "rata_rata_siklus": round(c_sum / t_botol, 3) if t_botol > 0 else 0.0,
            }
            overall_total_botol += t_botol
            overall_botol_gagal += b_gagal
            overall_cycle_sum += c_sum

    overall_avg_cycle = (
        round(overall_cycle_sum / overall_total_botol, 3)
        if overall_total_botol > 0
        else 0.0
    )

    # =========================================================================
    # 2. Hitung Total Durasi Darurat (E-stop)
    # =========================================================================
    estop_tekan_jenis = settings.EVENT_JENIS_ESTOP_TEKAN
    estop_lepas_jenis = settings.EVENT_JENIS_ESTOP_LEPAS

    match_event: Dict[str, Any] = {
        "mesin_id": id,
        "jenis": {"$in": [estop_tekan_jenis, estop_lepas_jenis]},
    }
    if sesi_id:
        match_event["sesi_id"] = sesi_id
    if norm_pengguna:
        match_event["pengguna"] = norm_pengguna

    cursor_event = db.event.find(match_event).sort([("sesi_id", 1), ("waktu", 1)])
    events = await cursor_event.to_list(length=None)

    now_utc = datetime.now(timezone.utc)
    total_durasi_darurat = 0.0
    user_durasi_darurat: Dict[str, float] = {}

    # Kelompokkan event per sesi_id
    sesi_events: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        s_id = ev.get("sesi_id", "")
        sesi_events.setdefault(s_id, []).append(ev)

    for s_id, ev_list in sesi_events.items():
        active_tekan_waktu: Optional[datetime] = None
        sesi_user: Optional[str] = None

        for ev in ev_list:
            if not sesi_user and ev.get("pengguna"):
                sesi_user = ev["pengguna"]

            ev_waktu = ev["waktu"]
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

                    # Potong sesuai rentang [dari, sampai] jika diminta
                    start_effective = max(t_start, dt_dari) if dt_dari else t_start
                    end_effective = min(t_end, dt_sampai) if dt_sampai else t_end

                    if end_effective > start_effective:
                        dur = (end_effective - start_effective).total_seconds()
                        total_durasi_darurat += dur
                        if sesi_user:
                            user_durasi_darurat[sesi_user] = (
                                user_durasi_darurat.get(sesi_user, 0.0) + dur
                            )

                    active_tekan_waktu = None

        # Jika masih dalam kondisi ditekan tanpa lepas
        if active_tekan_waktu is not None:
            t_start = active_tekan_waktu
            t_end = dt_sampai if dt_sampai else now_utc

            start_effective = max(t_start, dt_dari) if dt_dari else t_start
            end_effective = min(t_end, dt_sampai) if dt_sampai else t_end

            if end_effective > start_effective:
                dur = (end_effective - start_effective).total_seconds()
                total_durasi_darurat += dur
                if sesi_user:
                    user_durasi_darurat[sesi_user] = (
                        user_durasi_darurat.get(sesi_user, 0.0) + dur
                    )

    # =========================================================================
    # 3. Bentuk Rincian per Pengguna jika pengguna tidak difilter
    # =========================================================================
    rincian_pengguna: Optional[Dict[str, RingkasanStatistik]] = None
    if not norm_pengguna:
        rincian_pengguna = {}
        all_users = set(user_botol_stats.keys()).union(user_durasi_darurat.keys())
        for u in sorted(all_users):
            b_data = user_botol_stats.get(u, {})
            u_botol = b_data.get("total_botol", 0)
            u_gagal = b_data.get("botol_gagal", 0)
            u_avg = b_data.get("rata_rata_siklus", 0.0)
            u_durasi = round(user_durasi_darurat.get(u, 0.0), 3)
            rincian_pengguna[u] = RingkasanStatistik(
                jumlah_botol=u_botol,
                botol_gagal=u_gagal,
                rata_rata_waktu_siklus_detik=u_avg,
                total_durasi_darurat_detik=u_durasi,
            )

    return RingkasanResponse(
        mesin_id=id,
        sesi_id=sesi_id,
        pengguna=norm_pengguna,
        rentang={
            "dari": dt_dari.isoformat() if dt_dari else None,
            "sampai": dt_sampai.isoformat() if dt_sampai else None,
        },
        jumlah_botol=overall_total_botol,
        botol_gagal=overall_botol_gagal,
        rata_rata_waktu_siklus_detik=overall_avg_cycle,
        total_durasi_darurat_detik=round(total_durasi_darurat, 3),
        rincian_pengguna=rincian_pengguna,
    )


@router.get(
    "/{id}/event",
    summary="Ambil riwayat event mesin untuk monitoring",
)
async def ambil_riwayat_event(
    id: str,
    response: Response,
    jenis: Optional[str] = Query(None, description="Filter nama jenis event (tunggal atau koma dipisahkan)"),
    dari: Optional[str] = Query(None, description="Awal rentang waktu (ISO 8601 UTC)"),
    sampai: Optional[str] = Query(None, description="Akhir rentang waktu (ISO 8601 UTC)"),
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan sesi_id"),
    pengguna: Optional[str] = Query(None, description="Filter berdasarkan pengguna"),
    sumber: Optional[str] = Query(None, description="Filter berdasarkan sumber kejadian (pemain/sistem/operator/esp32)"),
    mode: Optional[str] = Query(None, description="Filter berdasarkan mode mesin sebelum atau sesudah"),
    page: Optional[int] = Query(None, ge=1, description="Nomor halaman pagination (mulai dari 1)"),
    skip: int = Query(0, ge=0, description="Jumlah data yang dilewati (skip)"),
    limit: int = Query(100, ge=1, le=1000, description="Jumlah data maksimal per halaman (1–1000, default 100)"),
    wrap: bool = Query(False, description="Jika true, mengembalikan response dibungkus metadata pagination"),
    _: Optional[str] = Depends(verify_read_access),
):
    """Membaca daftar event mesin, terurut dari yang terbaru (waktu descending).

    Mendukung pagination, filter multi-kriteria (jenis, sesi_id, pengguna, sumber, mode, rentang waktu),
    serta menyertakan response header pagination (X-Total-Count, X-Page, X-Total-Pages, dll.).
    """
    db = get_db()
    clean_id = id.strip()
    query: Dict[str, Any] = {"mesin_id": clean_id}

    if jenis:
        clean_jenis = jenis.strip()
        if "," in clean_jenis:
            items = [j.strip() for j in clean_jenis.split(",") if j.strip()]
            query["jenis"] = {"$in": items}
        else:
            query["jenis"] = clean_jenis

    if sesi_id:
        query["sesi_id"] = sesi_id.strip()

    if pengguna:
        query["pengguna"] = pengguna.strip().lower()

    if sumber:
        query["sumber"] = sumber.strip().lower()

    if mode:
        clean_mode = mode.strip()
        query["$or"] = [{"mode_sebelum": clean_mode}, {"mode_sesudah": clean_mode}]

    try:
        dt_dari = parse_iso8601_utc(dari) if dari else None
        dt_sampai = parse_iso8601_utc(sampai) if sampai else None
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

    if dt_dari or dt_sampai:
        time_filter: Dict[str, Any] = {}
        if dt_dari:
            time_filter["$gte"] = dt_dari
        if dt_sampai:
            time_filter["$lte"] = dt_sampai
        query["waktu"] = time_filter

    effective_skip = (page - 1) * limit if page is not None else skip

    # Query MongoDB dengan compound index {mesin_id: 1, waktu: -1}
    cursor = (
        db.event.find(query)
        .sort([("waktu", -1), ("_id", -1)])
        .skip(effective_skip)
        .limit(limit)
    )

    events = []
    async for doc in cursor:
        events.append(_serialize_doc(doc))

    # Hitung total dokumen yang cocok untuk header dan metadata pagination
    total_count = await db.event.count_documents(query)
    current_page = page if page is not None else ((effective_skip // limit) + 1)
    total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0

    response.headers["X-Total-Count"] = str(total_count)
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Skip"] = str(effective_skip)
    response.headers["X-Page"] = str(current_page)
    response.headers["X-Total-Pages"] = str(total_pages)

    if wrap:
        return {
            "total": total_count,
            "page": current_page,
            "limit": limit,
            "skip": effective_skip,
            "total_pages": total_pages,
            "items": events,
        }

    return events
