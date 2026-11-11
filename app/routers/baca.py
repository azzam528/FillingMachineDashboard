"""Router untuk endpoint baca: status mesin, telemetri, event, ringkasan, botol, downtime, dan laporan (prefix /api/v1 dan /api)."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.auth import verify_read_access
from app.config import Settings, get_settings
from app.db import get_db
from app.models import (
    DowntimeResponse,
    KejadianDowntimeItem,
    LaporanDowntimeSection,
    LaporanKualitasSection,
    LaporanProduksiSection,
    LaporanResponse,
    RingkasanResponse,
    RingkasanStatistik,
    parse_iso8601_utc,
)

router = APIRouter(prefix="/mesin", tags=["Baca Data & MES Analytics"])


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


def _format_botol_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Format dokumen botol lengkap dengan durasi siklus per botol untuk traceability."""
    if not doc:
        return None
    w_masuk = doc.get("waktu_masuk")
    w_keluar = doc.get("waktu_keluar")
    serialized = _serialize_doc(doc)
    if isinstance(w_masuk, datetime) and isinstance(w_keluar, datetime):
        durasi = (w_keluar - w_masuk).total_seconds()
        serialized["durasi_siklus_detik"] = round(durasi, 3)
    return serialized


def _hitung_downtime_dan_kejadian(
    events: List[Dict[str, Any]],
    dt_dari: Optional[datetime] = None,
    dt_sampai: Optional[datetime] = None,
    estop_tekan_jenis: str = "estop_tekan",
    estop_lepas_jenis: str = "estop_lepas",
) -> Tuple[float, int, List[Dict[str, Any]], Dict[str, float]]:
    """Menghitung total durasi darurat E-stop berpasangan dan rincian per kejadian downtime."""
    now_utc = datetime.now(timezone.utc)
    total_durasi_darurat = 0.0
    user_durasi_darurat: Dict[str, float] = {}
    kejadian_list: List[Dict[str, Any]] = []

    # Kelompokkan event per sesi_id
    sesi_events: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        s_id = ev.get("sesi_id", "")
        sesi_events.setdefault(s_id, []).append(ev)

    for s_id, ev_list in sesi_events.items():
        active_tekan_waktu: Optional[datetime] = None
        active_pesan: Optional[str] = None
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
                    active_pesan = ev.get("pesan")
            elif jenis == estop_lepas_jenis:
                if active_tekan_waktu is not None:
                    t_start = active_tekan_waktu
                    t_end = ev_waktu

                    # Potong rentang jika diminta
                    start_eff = max(t_start, dt_dari) if dt_dari else t_start
                    end_eff = min(t_end, dt_sampai) if dt_sampai else t_end

                    if end_eff > start_eff:
                        dur = (end_eff - start_eff).total_seconds()
                        total_durasi_darurat += dur
                        if sesi_user:
                            user_durasi_darurat[sesi_user] = (
                                user_durasi_darurat.get(sesi_user, 0.0) + dur
                            )
                        kejadian_list.append({
                            "sesi_id": s_id,
                            "pengguna": sesi_user,
                            "waktu_mulai": t_start.isoformat().replace("+00:00", "Z"),
                            "waktu_selesai": t_end.isoformat().replace("+00:00", "Z"),
                            "durasi_detik": round((t_end - t_start).total_seconds(), 3),
                            "status": "SELESAI",
                            "pesan": active_pesan,
                        })

                    active_tekan_waktu = None
                    active_pesan = None

        # Jika masih aktif belum dilepas
        if active_tekan_waktu is not None:
            t_start = active_tekan_waktu
            t_end = dt_sampai if dt_sampai else now_utc

            start_eff = max(t_start, dt_dari) if dt_dari else t_start
            end_eff = min(t_end, dt_sampai) if dt_sampai else t_end

            if end_eff > start_eff:
                dur = (end_eff - start_eff).total_seconds()
                total_durasi_darurat += dur
                if sesi_user:
                    user_durasi_darurat[sesi_user] = (
                        user_durasi_darurat.get(sesi_user, 0.0) + dur
                    )
                kejadian_list.append({
                    "sesi_id": s_id,
                    "pengguna": sesi_user,
                    "waktu_mulai": t_start.isoformat().replace("+00:00", "Z"),
                    "waktu_selesai": None,
                    "durasi_detik": round((t_end - t_start).total_seconds(), 3),
                    "status": "AKTIF",
                    "pesan": active_pesan,
                })

    return total_durasi_darurat, len(kejadian_list), kejadian_list, user_durasi_darurat


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
    """Membaca 1 data telemetri terakhir mesin (sort waktu descending)."""
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
    summary="Ambil ringkasan produksi dan kualitas mesin",
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
    """Menghitung ringkasan produksi, metrik kualitas (botol OK/gagal/kategori), dan downtime (E-stop)."""
    db = get_db()
    clean_id = id.strip()

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
    # 1. Agregasi Data Botol (Produksi & Kualitas)
    # =========================================================================
    match_botol: Dict[str, Any] = {"mesin_id": clean_id}
    if sesi_id:
        match_botol["sesi_id"] = sesi_id.strip()
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
    overall_botol_ok = 0
    overall_botol_gagal = 0
    overall_tidak_penuh = 0
    overall_tanpa_tutup = 0
    overall_cycle_sum = 0.0

    if norm_pengguna:
        # Query untuk pengguna tunggal
        pipeline_single = [
            {"$match": match_botol},
            {
                "$group": {
                    "_id": None,
                    "total_botol": {"$sum": 1},
                    "botol_ok": {
                        "$sum": {"$cond": [{"$eq": ["$status", "OK"]}, 1, 0]}
                    },
                    "botol_gagal": {
                        "$sum": {"$cond": [{"$ne": ["$status", "OK"]}, 1, 0]}
                    },
                    "tidak_penuh": {
                        "$sum": {"$cond": [{"$eq": ["$status", "TIDAK_PENUH"]}, 1, 0]}
                    },
                    "tanpa_tutup": {
                        "$sum": {"$cond": [{"$eq": ["$status", "TANPA_TUTUP"]}, 1, 0]}
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
            overall_botol_ok = int(res[0].get("botol_ok", 0))
            overall_botol_gagal = int(res[0].get("botol_gagal", 0))
            overall_tidak_penuh = int(res[0].get("tidak_penuh", 0))
            overall_tanpa_tutup = int(res[0].get("tanpa_tutup", 0))
            overall_cycle_sum = float(res[0].get("total_siklus_detik", 0.0))
    else:
        # Group by pengguna untuk menyajikan rincian per pengguna
        pipeline_per_user = [
            {"$match": match_botol},
            {
                "$group": {
                    "_id": "$pengguna",
                    "total_botol": {"$sum": 1},
                    "botol_ok": {
                        "$sum": {"$cond": [{"$eq": ["$status", "OK"]}, 1, 0]}
                    },
                    "botol_gagal": {
                        "$sum": {"$cond": [{"$ne": ["$status", "OK"]}, 1, 0]}
                    },
                    "tidak_penuh": {
                        "$sum": {"$cond": [{"$eq": ["$status", "TIDAK_PENUH"]}, 1, 0]}
                    },
                    "tanpa_tutup": {
                        "$sum": {"$cond": [{"$eq": ["$status", "TANPA_TUTUP"]}, 1, 0]}
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
            b_ok = int(row.get("botol_ok", 0))
            b_gagal = int(row.get("botol_gagal", 0))
            t_penuh = int(row.get("tidak_penuh", 0))
            t_tutup = int(row.get("tanpa_tutup", 0))
            c_sum = float(row.get("total_siklus_detik", 0.0))
            user_botol_stats[u] = {
                "total_botol": t_botol,
                "botol_ok": b_ok,
                "botol_gagal": b_gagal,
                "kategori_kegagalan": {
                    "TIDAK_PENUH": t_penuh,
                    "TANPA_TUTUP": t_tutup,
                },
                "total_siklus_detik": c_sum,
                "rata_rata_siklus": round(c_sum / t_botol, 3) if t_botol > 0 else 0.0,
            }
            overall_total_botol += t_botol
            overall_botol_ok += b_ok
            overall_botol_gagal += b_gagal
            overall_tidak_penuh += t_penuh
            overall_tanpa_tutup += t_tutup
            overall_cycle_sum += c_sum

    overall_avg_cycle = (
        round(overall_cycle_sum / overall_total_botol, 3)
        if overall_total_botol > 0
        else 0.0
    )

    # =========================================================================
    # 2. Hitung Total Durasi Darurat (Downtime E-stop)
    # =========================================================================
    estop_tekan_jenis = settings.EVENT_JENIS_ESTOP_TEKAN
    estop_lepas_jenis = settings.EVENT_JENIS_ESTOP_LEPAS

    match_event: Dict[str, Any] = {
        "mesin_id": clean_id,
        "jenis": {"$in": [estop_tekan_jenis, estop_lepas_jenis]},
    }
    if sesi_id:
        match_event["sesi_id"] = sesi_id.strip()
    if norm_pengguna:
        match_event["pengguna"] = norm_pengguna

    cursor_event = db.event.find(match_event).sort([("sesi_id", 1), ("waktu", 1)])
    events = await cursor_event.to_list(length=None)

    total_durasi_darurat, _, _, user_durasi_darurat = _hitung_downtime_dan_kejadian(
        events, dt_dari, dt_sampai, estop_tekan_jenis, estop_lepas_jenis
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
            u_ok = b_data.get("botol_ok", u_botol - b_data.get("botol_gagal", 0))
            u_gagal = b_data.get("botol_gagal", 0)
            u_kat = b_data.get("kategori_kegagalan", {})
            u_avg = b_data.get("rata_rata_siklus", 0.0)
            u_durasi = round(user_durasi_darurat.get(u, 0.0), 3)
            rincian_pengguna[u] = RingkasanStatistik(
                jumlah_botol=u_botol,
                botol_gagal=u_gagal,
                rata_rata_waktu_siklus_detik=u_avg,
                total_durasi_darurat_detik=u_durasi,
                botol_ok=u_ok,
                kategori_kegagalan=u_kat,
            )

    return RingkasanResponse(
        mesin_id=clean_id,
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
        botol_ok=overall_botol_ok,
        kategori_kegagalan={
            "TIDAK_PENUH": overall_tidak_penuh,
            "TANPA_TUTUP": overall_tanpa_tutup,
        },
        rincian_pengguna=rincian_pengguna,
    )


@router.get(
    "/{id}/botol",
    summary="Ambil riwayat botol untuk Traceability dan analisis Kualitas",
)
async def ambil_daftar_botol(
    id: str,
    response: Response,
    nomor: Optional[int] = Query(None, ge=1, description="Cari berdasarkan nomor urut botol spesifik"),
    status: Optional[str] = Query(None, description="Filter status inspeksi botol (OK, TIDAK_PENUH, TANPA_TUTUP)"),
    slot: Optional[int] = Query(None, ge=0, description="Filter nomor slot turret"),
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    pengguna: Optional[str] = Query(None, description="Filter berdasarkan nama pengguna"),
    dari: Optional[str] = Query(None, description="Awal rentang waktu keluar botol (ISO 8601 UTC)"),
    sampai: Optional[str] = Query(None, description="Akhir rentang waktu keluar botol (ISO 8601 UTC)"),
    page: Optional[int] = Query(None, ge=1, description="Nomor halaman untuk pagination (mulai dari 1)"),
    skip: int = Query(0, ge=0, description="Jumlah data dilewati (skip)"),
    limit: int = Query(50, ge=1, le=1000, description="Jumlah data per halaman (1–1000, default 50)"),
    wrap: bool = Query(False, description="Jika true, return objek dengan metadata pagination"),
    _: Optional[str] = Depends(verify_read_access),
):
    """Membaca daftar riwayat produksi botol untuk Traceability dan analisis mutu kualitas.

    Menampilkan informasi slot, waktu proses, level isi, tutup, status inspeksi,
    serta durasi siklus aktual botol.
    """
    db = get_db()
    clean_id = id.strip()
    query: Dict[str, Any] = {"mesin_id": clean_id}

    if nomor is not None:
        query["nomor"] = nomor

    if status:
        query["status"] = status.strip().upper()

    if slot is not None:
        query["slot"] = slot

    if sesi_id:
        query["sesi_id"] = sesi_id.strip()

    if pengguna:
        query["pengguna"] = pengguna.strip().lower()

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
        query["waktu_keluar"] = time_filter

    effective_skip = (page - 1) * limit if page is not None else skip

    cursor = (
        db.botol.find(query)
        .sort([("waktu_keluar", -1), ("_id", -1)])
        .skip(effective_skip)
        .limit(limit)
    )

    items = []
    async for doc in cursor:
        items.append(_format_botol_doc(doc))

    total_count = await db.botol.count_documents(query)
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
            "items": items,
        }

    return items


@router.get(
    "/{id}/botol/{nomor}",
    summary="Ambil detail traceability 1 botol berdasarkan nomor urut",
)
async def ambil_detail_botol(
    id: str,
    nomor: int,
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    _: Optional[str] = Depends(verify_read_access),
):
    """Membaca detail 1 dokumen botol untuk penelusuran (traceability) inspeksi fisik."""
    db = get_db()
    clean_id = id.strip()
    query: Dict[str, Any] = {"mesin_id": clean_id, "nomor": nomor}
    if sesi_id:
        query["sesi_id"] = sesi_id.strip()

    doc = await db.botol.find_one(query, sort=[("waktu_keluar", -1)])
    if not doc:
        msg = f"Botol dengan nomor {nomor} untuk mesin '{id}' tidak ditemukan"
        if sesi_id:
            msg += f" pada sesi '{sesi_id}'"
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=msg,
        )
    return _format_botol_doc(doc)


@router.get(
    "/{id}/downtime",
    response_model=DowntimeResponse,
    summary="Ambil riwayat kejadian darurat dan analisis downtime mesin",
)
async def ambil_downtime_mesin(
    id: str,
    dari: Optional[str] = Query(None, description="Awal rentang waktu downtime (ISO 8601 UTC)"),
    sampai: Optional[str] = Query(None, description="Akhir rentang waktu downtime (ISO 8601 UTC)"),
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    pengguna: Optional[str] = Query(None, description="Filter berdasarkan pengguna"),
    _: Optional[str] = Depends(verify_read_access),
    settings: Settings = Depends(get_settings),
):
    """Menganalisis downtime mesin (durasi total, frekuensi, dan riwayat setiap penekanan tombol darurat E-stop)."""
    db = get_db()
    clean_id = id.strip()

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

    estop_tekan_jenis = settings.EVENT_JENIS_ESTOP_TEKAN
    estop_lepas_jenis = settings.EVENT_JENIS_ESTOP_LEPAS

    match_event: Dict[str, Any] = {
        "mesin_id": clean_id,
        "jenis": {"$in": [estop_tekan_jenis, estop_lepas_jenis]},
    }
    if sesi_id:
        match_event["sesi_id"] = sesi_id.strip()
    if norm_pengguna:
        match_event["pengguna"] = norm_pengguna

    cursor_event = db.event.find(match_event).sort([("sesi_id", 1), ("waktu", 1)])
    events = await cursor_event.to_list(length=None)

    total_durasi, jumlah_kejadian, kejadian_items, user_durasi = _hitung_downtime_dan_kejadian(
        events, dt_dari, dt_sampai, estop_tekan_jenis, estop_lepas_jenis
    )

    rincian_user = {k: round(v, 3) for k, v in user_durasi.items()} if not norm_pengguna else None

    return DowntimeResponse(
        mesin_id=clean_id,
        rentang={
            "dari": dt_dari.isoformat() if dt_dari else None,
            "sampai": dt_sampai.isoformat() if dt_sampai else None,
        },
        total_durasi_downtime_detik=round(total_durasi, 3),
        jumlah_kejadian_downtime=jumlah_kejadian,
        kejadian=[KejadianDowntimeItem(**k) for k in kejadian_items],
        rincian_pengguna=rincian_user,
    )


@router.get(
    "/{id}/laporan",
    response_model=LaporanResponse,
    summary="Ambil laporan terpadu produksi, kualitas, dan downtime",
)
async def ambil_laporan_mesin(
    id: str,
    dari: Optional[str] = Query(None, description="Awal rentang waktu laporan (ISO 8601 UTC)"),
    sampai: Optional[str] = Query(None, description="Akhir rentang waktu laporan (ISO 8601 UTC)"),
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    pengguna: Optional[str] = Query(None, description="Filter berdasarkan pengguna"),
    _: Optional[str] = Depends(verify_read_access),
    settings: Settings = Depends(get_settings),
):
    """Menyajikan laporan terpadu untuk halaman Laporan MES (Produksi, Kualitas, dan Downtime)."""
    db = get_db()
    clean_id = id.strip()

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

    # 1. Agregasi Botol
    match_botol: Dict[str, Any] = {"mesin_id": clean_id}
    if sesi_id:
        match_botol["sesi_id"] = sesi_id.strip()
    if norm_pengguna:
        match_botol["pengguna"] = norm_pengguna

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
                "botol_ok": {
                    "$sum": {"$cond": [{"$eq": ["$status", "OK"]}, 1, 0]}
                },
                "botol_gagal": {
                    "$sum": {"$cond": [{"$ne": ["$status", "OK"]}, 1, 0]}
                },
                "tidak_penuh": {
                    "$sum": {"$cond": [{"$eq": ["$status", "TIDAK_PENUH"]}, 1, 0]}
                },
                "tanpa_tutup": {
                    "$sum": {"$cond": [{"$eq": ["$status", "TANPA_TUTUP"]}, 1, 0]}
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

    res_b = await db.botol.aggregate(pipeline_botol).to_list(1)
    total_b = 0
    ok_b = 0
    gagal_b = 0
    tidak_penuh_b = 0
    tanpa_tutup_b = 0
    cycle_sum_b = 0.0

    if res_b:
        total_b = int(res_b[0].get("total_botol", 0))
        ok_b = int(res_b[0].get("botol_ok", 0))
        gagal_b = int(res_b[0].get("botol_gagal", 0))
        tidak_penuh_b = int(res_b[0].get("tidak_penuh", 0))
        tanpa_tutup_b = int(res_b[0].get("tanpa_tutup", 0))
        cycle_sum_b = float(res_b[0].get("total_siklus_detik", 0.0))

    avg_cycle = round(cycle_sum_b / total_b, 3) if total_b > 0 else 0.0
    yield_rate = round((ok_b / total_b) * 100, 2) if total_b > 0 else 0.0

    # 2. Agregasi Downtime E-Stop
    estop_tekan_jenis = settings.EVENT_JENIS_ESTOP_TEKAN
    estop_lepas_jenis = settings.EVENT_JENIS_ESTOP_LEPAS

    match_event: Dict[str, Any] = {
        "mesin_id": clean_id,
        "jenis": {"$in": [estop_tekan_jenis, estop_lepas_jenis]},
    }
    if sesi_id:
        match_event["sesi_id"] = sesi_id.strip()
    if norm_pengguna:
        match_event["pengguna"] = norm_pengguna

    cursor_event = db.event.find(match_event).sort([("sesi_id", 1), ("waktu", 1)])
    events = await cursor_event.to_list(length=None)

    total_durasi, jumlah_kejadian, _, _ = _hitung_downtime_dan_kejadian(
        events, dt_dari, dt_sampai, estop_tekan_jenis, estop_lepas_jenis
    )

    return LaporanResponse(
        mesin_id=clean_id,
        rentang={
            "dari": dt_dari.isoformat() if dt_dari else None,
            "sampai": dt_sampai.isoformat() if dt_sampai else None,
        },
        filter={
            "sesi_id": sesi_id,
            "pengguna": norm_pengguna,
        },
        produksi=LaporanProduksiSection(
            total_botol=total_b,
            rata_rata_waktu_siklus_detik=avg_cycle,
            total_waktu_siklus_detik=round(cycle_sum_b, 3),
        ),
        kualitas=LaporanKualitasSection(
            botol_ok=ok_b,
            botol_gagal=gagal_b,
            persentase_ok=yield_rate,
            kategori_kegagalan={
                "TIDAK_PENUH": tidak_penuh_b,
                "TANPA_TUTUP": tanpa_tutup_b,
            },
        ),
        downtime=LaporanDowntimeSection(
            total_durasi_detik=round(total_durasi, 3),
            jumlah_kejadian=jumlah_kejadian,
        ),
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
    """Membaca daftar event mesin, terurut dari yang terbaru (waktu descending)."""
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
