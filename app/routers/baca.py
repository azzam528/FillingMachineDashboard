"""Router untuk endpoint baca: status mesin, telemetri, event, ringkasan, botol, downtime, dan laporan (prefix /api)."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.auth import verify_read_access
from app.config import Settings, get_settings
from app.db import get_db
from app.kpi import (
    calculate_actual_cycle_time_avg,
    calculate_availability,
    calculate_effective_capacity_per_hour,
    calculate_level_isi_stats,
    calculate_mtbf,
    calculate_mttr,
    calculate_oee,
    calculate_performance,
    calculate_production_time,
    calculate_quality,
    calculate_six_big_losses,
    calculate_theoretical_capacity,
    calculate_wip_total,
)
from app.models import (
    DowntimeResponse,
    InventoriResponse,
    KapasitasResponse,
    KejadianDowntimeItem,
    KualitasAnalisisResponse,
    LaporanDowntimeSection,
    LaporanKualitasSection,
    LaporanProduksiSection,
    LaporanResponse,
    LeadTimeResponse,
    OEEResponse,
    ReliabilityResponse,
    RingkasanResponse,
    RingkasanStatistik,
    WIPResponse,
    parse_iso8601_utc,
)

router = APIRouter(prefix="/mesin")


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
    tags=["Live Monitoring & Konfigurasi Mesin"],
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
    tags=["Live Monitoring & Konfigurasi Mesin"],
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
    tags=["Live Monitoring & Konfigurasi Mesin"],
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
    tags=["Analitik MES & Laporan"],
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
    tags=["Analitik MES & Laporan"],
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
    tags=["Analitik MES & Laporan"],
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
    tags=["Analitik MES & Laporan"],
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
    tags=["Analitik MES & Laporan"],
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
    tags=["Live Monitoring & Konfigurasi Mesin"],
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


# ============================================================================
# Endpoint Baru Sesuai Spesifikasi Web MES
# ============================================================================

@router.get(
    "/{id}/oee",
    response_model=OEEResponse,
    summary="Ambil metrik OEE, Availability, Performance, Quality, dan Six Big Losses",
    tags=["Analitik MES & Laporan"],
)
async def ambil_oee_mesin(
    id: str,
    batch_ke: Optional[int] = Query(None, ge=1, description="Nomor batch tertentu"),
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    pengguna: Optional[str] = Query(None, description="Filter berdasarkan nama pengguna"),
    dari: Optional[str] = Query(None, description="Awal rentang waktu (ISO 8601 UTC)"),
    sampai: Optional[str] = Query(None, description="Akhir rentang waktu (ISO 8601 UTC)"),
    _: Optional[str] = Depends(verify_read_access),
    settings: Settings = Depends(get_settings),
):
    """Menghitung metrik OEE, Availability, Performance, Quality, dan rincian Six Big Losses."""
    db = get_db()
    clean_id = id.strip()

    # Cek dokumen batch terlebih dahulu
    query_batch: Dict[str, Any] = {"mesin_id": clean_id}
    if batch_ke is not None:
        query_batch["batch_ke"] = batch_ke
    if sesi_id:
        query_batch["sesi_id"] = sesi_id.strip()
    if pengguna:
        query_batch["pengguna"] = pengguna.strip().lower()

    batch_doc = await db.batch.find_one(query_batch, sort=[("batch_ke", -1), ("waktu_selesai", -1)])

    if batch_doc:
        planned = float(batch_doc.get("planned_production_time") or 0.0)
        unplanned = float(batch_doc.get("downtime_unplanned") or 0.0)
        setup = float(batch_doc.get("setup_time") or 0.0)
        starvation = float(batch_doc.get("starvation_downtime") or 0.0)
        packaging = float(batch_doc.get("packaging_time") or 0.0)
        botol_selesai = int(batch_doc.get("botol_selesai") or 0)
        botol_ok = int(batch_doc.get("botol_ok") or 0)
        botol_reject = int(batch_doc.get("botol_reject") or 0)
        ideal_ct = float(batch_doc.get("ideal_cycle_time") or settings.IDEAL_CYCLE_TIME)

        prod_time = calculate_production_time(planned, unplanned, setup, starvation, packaging)
        avail = calculate_availability(prod_time, planned)
        perf = calculate_performance(ideal_ct, botol_selesai, prod_time)
        qual = calculate_quality(botol_ok, botol_selesai)
        oee_val = calculate_oee(avail, perf, qual)

        losses = calculate_six_big_losses(
            downtime_unplanned=unplanned,
            setup_time=setup,
            starvation_downtime=starvation,
            packaging_time=packaging,
            production_time=prod_time,
            ideal_cycle_time=ideal_ct,
            botol_selesai=botol_selesai,
            botol_reject=botol_reject,
        )

        return OEEResponse(
            mesin_id=clean_id,
            sesi_id=batch_doc.get("sesi_id"),
            batch_ke=batch_doc.get("batch_ke"),
            availability=avail,
            performance=perf,
            quality=qual,
            oee=oee_val,
            availability_pct=round(avail * 100.0, 2),
            performance_pct=round(perf * 100.0, 2),
            quality_pct=round(qual * 100.0, 2),
            oee_pct=round((oee_val * 100.0) + 1e-7, 2),
            losses=losses,
            operating_time_detik=prod_time,
            planned_time_detik=planned,
            kpi_mismatch=batch_doc.get("kpi_mismatch"),
        )

    # Fallback jika belum ada batch: periksa telemetri terakhir
    query_tel: Dict[str, Any] = {"mesin_id": clean_id}
    if sesi_id:
        query_tel["sesi_id"] = sesi_id.strip()
    if pengguna:
        query_tel["pengguna"] = pengguna.strip().lower()

    tel_doc = await db.telemetri.find_one(query_tel, sort=[("waktu", -1)])
    if not tel_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data OEE belum tersedia untuk mesin '{id}'",
        )

    planned = float(tel_doc.get("planned_production_time") or 0.0)
    unplanned = float(tel_doc.get("downtime_unplanned") or 0.0)
    setup = float(tel_doc.get("setup_time") or 0.0)
    starvation = float(tel_doc.get("starvation_downtime") or 0.0)
    packaging = float(tel_doc.get("packaging_time") or 0.0)
    botol_selesai = int(tel_doc.get("botol_selesai") or 0)
    botol_ok = int(tel_doc.get("botol_ok") or 0)
    botol_reject = int(tel_doc.get("botol_reject") or 0)
    ideal_ct = float(tel_doc.get("ideal_cycle_time") or settings.IDEAL_CYCLE_TIME)

    prod_time = calculate_production_time(planned, unplanned, setup, starvation, packaging)
    avail = calculate_availability(prod_time, planned)
    perf = calculate_performance(ideal_ct, botol_selesai, prod_time)
    qual = calculate_quality(botol_ok, botol_selesai)
    oee_val = calculate_oee(avail, perf, qual)

    losses = calculate_six_big_losses(
        downtime_unplanned=unplanned,
        setup_time=setup,
        starvation_downtime=starvation,
        packaging_time=packaging,
        production_time=prod_time,
        ideal_cycle_time=ideal_ct,
        botol_selesai=botol_selesai,
        botol_reject=botol_reject,
    )

    return OEEResponse(
        mesin_id=clean_id,
        sesi_id=tel_doc.get("sesi_id"),
        batch_ke=tel_doc.get("batch_ke"),
        availability=avail,
        performance=perf,
        quality=qual,
        oee=oee_val,
        availability_pct=round(avail * 100.0, 2),
        performance_pct=round(perf * 100.0, 2),
        quality_pct=round(qual * 100.0, 2),
        oee_pct=round((oee_val * 100.0) + 1e-7, 2),
        losses=losses,
        operating_time_detik=prod_time,
        planned_time_detik=planned,
        kpi_mismatch=None,
    )


@router.get(
    "/{id}/batch",
    summary="Ambil daftar riwayat batch produksi mesin",
    tags=["Analitik MES & Laporan"],
)
async def ambil_daftar_batch(
    id: str,
    response: Response,
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    pengguna: Optional[str] = Query(None, description="Filter berdasarkan pengguna"),
    dari: Optional[str] = Query(None, description="Awal rentang waktu selesai (ISO 8601 UTC)"),
    sampai: Optional[str] = Query(None, description="Akhir rentang waktu selesai (ISO 8601 UTC)"),
    page: Optional[int] = Query(None, ge=1, description="Nomor halaman pagination"),
    skip: int = Query(0, ge=0, description="Jumlah data dilewati"),
    limit: int = Query(50, ge=1, le=1000, description="Jumlah data per halaman"),
    wrap: bool = Query(False, description="Jika true, return objek dengan metadata pagination"),
    _: Optional[str] = Depends(verify_read_access),
):
    """Membaca riwayat batch produksi terurut dari batch terbaru."""
    db = get_db()
    clean_id = id.strip()
    query: Dict[str, Any] = {"mesin_id": clean_id}

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
        query["waktu_selesai"] = time_filter

    effective_skip = (page - 1) * limit if page is not None else skip

    cursor = (
        db.batch.find(query)
        .sort([("batch_ke", -1), ("waktu_selesai", -1)])
        .skip(effective_skip)
        .limit(limit)
    )

    items = []
    async for doc in cursor:
        items.append(_serialize_doc(doc))

    total_count = await db.batch.count_documents(query)
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
    "/{id}/batch/{batch_ke}",
    summary="Ambil detail 1 batch produksi berdasarkan nomor batch",
    tags=["Analitik MES & Laporan"],
)
async def ambil_detail_batch(
    id: str,
    batch_ke: int,
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    _: Optional[str] = Depends(verify_read_access),
):
    """Membaca dokumen detail 1 batch produksi."""
    db = get_db()
    clean_id = id.strip()
    query: Dict[str, Any] = {"mesin_id": clean_id, "batch_ke": batch_ke}
    if sesi_id:
        query["sesi_id"] = sesi_id.strip()

    doc = await db.batch.find_one(query, sort=[("waktu_selesai", -1)])
    if not doc:
        msg = f"Batch nomor {batch_ke} untuk mesin '{id}' tidak ditemukan"
        if sesi_id:
            msg += f" pada sesi '{sesi_id}'"
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=msg,
        )
    return _serialize_doc(doc)


@router.get(
    "/{id}/wip",
    response_model=WIPResponse,
    summary="Ambil status Work-in-Process (WIP) mesin saat ini",
    tags=["Analitik MES & Laporan"],
)
async def ambil_wip_mesin(
    id: str,
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    _: Optional[str] = Depends(verify_read_access),
    settings: Settings = Depends(get_settings),
):
    """Membaca metrik Work-in-Process (WIP) terkini dari stasiun peti, turret, dan kotak penampung."""
    db = get_db()
    clean_id = id.strip()

    mesin_doc = await db.mesin.find_one({"_id": clean_id})
    kap_peti = (mesin_doc.get("kapasitas_peti") if mesin_doc else None) or 30
    kap_turret = (mesin_doc.get("jumlah_slot") if mesin_doc else None) or 10
    kap_kotak = (mesin_doc.get("kapasitas_kotak") if mesin_doc else None) or 30
    kap_maksimal = kap_peti + kap_turret + kap_kotak

    query: Dict[str, Any] = {"mesin_id": clean_id}
    if sesi_id:
        query["sesi_id"] = sesi_id.strip()

    doc = await db.telemetri.find_one(query, sort=[("waktu", -1)])
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data telemetri untuk evaluasi WIP mesin '{id}' belum tersedia",
        )

    sisa_peti = int(doc.get("sisa_peti") or 0)
    wip_turret = int(doc.get("wip_turret") or 0)
    isi_kotak = int(doc.get("isi_kotak") or 0)
    isi_kotak_reject = int(doc.get("isi_kotak_reject") or 0)
    wip_tot = int(doc.get("wip_total") or calculate_wip_total(sisa_peti, wip_turret, isi_kotak))

    warning = wip_tot >= int(kap_maksimal * settings.WIP_WARNING_RATIO)
    waktu_str = doc.get("waktu").isoformat() if isinstance(doc.get("waktu"), datetime) else str(doc.get("waktu") or "")

    return WIPResponse(
        mesin_id=clean_id,
        wip_total=wip_tot,
        sisa_peti=sisa_peti,
        wip_turret=wip_turret,
        isi_kotak=isi_kotak,
        isi_kotak_reject=isi_kotak_reject,
        warning=warning,
        kapasitas_maksimal=kap_maksimal,
        waktu=waktu_str,
    )


@router.get(
    "/{id}/kualitas",
    response_model=KualitasAnalisisResponse,
    summary="Ambil analisis kualitas, Pareto reject, dan statistik level isi cairan",
    tags=["Analitik MES & Laporan"],
)
async def ambil_analisis_kualitas(
    id: str,
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    pengguna: Optional[str] = Query(None, description="Filter berdasarkan pengguna"),
    dari: Optional[str] = Query(None, description="Awal rentang waktu (ISO 8601 UTC)"),
    sampai: Optional[str] = Query(None, description="Akhir rentang waktu (ISO 8601 UTC)"),
    batch_ke: Optional[int] = Query(None, ge=1, description="Filter nomor batch"),
    _: Optional[str] = Depends(verify_read_access),
    settings: Settings = Depends(get_settings),
):
    """Menghitung First Pass Yield, diagram Pareto cacat produk, dan statistik SPC (Mean, UCL, LCL) level isi."""
    db = get_db()
    clean_id = id.strip()
    match_botol: Dict[str, Any] = {"mesin_id": clean_id}

    if sesi_id:
        match_botol["sesi_id"] = sesi_id.strip()
    if pengguna:
        match_botol["pengguna"] = pengguna.strip().lower()
    if batch_ke is not None:
        match_botol["batch_ke"] = batch_ke

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
        match_botol["waktu_keluar"] = time_filter

    pipeline = [
        {"$match": match_botol},
        {
            "$group": {
                "_id": None,
                "total_botol": {"$sum": 1},
                "botol_ok": {
                    "$sum": {"$cond": [{"$eq": ["$status", "OK"]}, 1, 0]}
                },
                "botol_reject": {
                    "$sum": {"$cond": [{"$ne": ["$status", "OK"]}, 1, 0]}
                },
                "tidak_penuh": {
                    "$sum": {"$cond": [{"$eq": ["$status", "TIDAK_PENUH"]}, 1, 0]}
                },
                "tanpa_tutup": {
                    "$sum": {"$cond": [{"$eq": ["$status", "TANPA_TUTUP"]}, 1, 0]}
                },
                "levels": {"$push": "$level_isi"},
            }
        },
    ]

    res = await db.botol.aggregate(pipeline).to_list(1)
    if not res:
        return KualitasAnalisisResponse(
            mesin_id=clean_id,
            total_botol=0,
            botol_ok=0,
            botol_reject=0,
            first_pass_yield_pct=0.0,
            pareto_reject={},
            level_isi_stats=calculate_level_isi_stats([], settings.BATAS_LULUS_QC),
        )

    row = res[0]
    total_b = int(row.get("total_botol", 0))
    ok_b = int(row.get("botol_ok", 0))
    reject_b = int(row.get("botol_reject", 0))
    tidak_penuh = int(row.get("tidak_penuh", 0))
    tanpa_tutup = int(row.get("tanpa_tutup", 0))
    levels = [float(x) for x in row.get("levels", []) if x is not None]

    fpy_pct = round((ok_b / total_b) * 100.0, 2) if total_b > 0 else 0.0
    pareto = {}
    if tidak_penuh > 0:
        pareto["TIDAK_PENUH"] = tidak_penuh
    if tanpa_tutup > 0:
        pareto["TANPA_TUTUP"] = tanpa_tutup

    stats = calculate_level_isi_stats(levels, settings.BATAS_LULUS_QC)

    return KualitasAnalisisResponse(
        mesin_id=clean_id,
        total_botol=total_b,
        botol_ok=ok_b,
        botol_reject=reject_b,
        first_pass_yield_pct=fpy_pct,
        pareto_reject=pareto,
        level_isi_stats=stats,
    )


@router.get(
    "/{id}/lead-time",
    response_model=LeadTimeResponse,
    summary="Ambil metrik Manufacturing Lead Time (MLT) botol dan batch",
    tags=["Analitik MES & Laporan"],
)
async def ambil_lead_time(
    id: str,
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    pengguna: Optional[str] = Query(None, description="Filter berdasarkan pengguna"),
    dari: Optional[str] = Query(None, description="Awal rentang waktu (ISO 8601 UTC)"),
    sampai: Optional[str] = Query(None, description="Akhir rentang waktu (ISO 8601 UTC)"),
    _: Optional[str] = Depends(verify_read_access),
):
    """Menghitung rata-rata Manufacturing Lead Time (MLT) per unit botol dan per batch."""
    db = get_db()
    clean_id = id.strip()

    match_botol: Dict[str, Any] = {"mesin_id": clean_id}
    match_batch: Dict[str, Any] = {"mesin_id": clean_id}

    if sesi_id:
        match_botol["sesi_id"] = sesi_id.strip()
        match_batch["sesi_id"] = sesi_id.strip()
    if pengguna:
        match_botol["pengguna"] = pengguna.strip().lower()
        match_batch["pengguna"] = pengguna.strip().lower()

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
        match_botol["waktu_keluar"] = time_filter
        match_batch["waktu_selesai"] = time_filter

    pipeline_botol = [
        {"$match": match_botol},
        {
            "$project": {
                "unit_mlt": {
                    "$cond": [
                        {"$gt": ["$unit_mlt_detik", 0]},
                        "$unit_mlt_detik",
                        {"$divide": [{"$subtract": ["$waktu_keluar", "$waktu_masuk"]}, 1000.0]},
                    ]
                },
                "durasi_isi": {
                    "$cond": [
                        {"$gt": ["$durasi_isi_detik", 0]},
                        "$durasi_isi_detik",
                        {
                            "$cond": [
                                {"$and": ["$waktu_isi_selesai", "$waktu_isi_mulai"]},
                                {"$divide": [{"$subtract": ["$waktu_isi_selesai", "$waktu_isi_mulai"]}, 1000.0]},
                                0.0,
                            ]
                        },
                    ]
                },
            }
        },
        {
            "$group": {
                "_id": None,
                "count": {"$sum": 1},
                "avg_unit_mlt": {"$avg": "$unit_mlt"},
                "avg_durasi_isi": {"$avg": "$durasi_isi"},
            }
        },
    ]

    pipeline_batch = [
        {"$match": match_batch},
        {
            "$project": {
                "batch_mlt": {
                    "$cond": [
                        {"$gt": ["$mlt_batch", 0]},
                        "$mlt_batch",
                        {"$divide": [{"$subtract": ["$waktu_selesai", "$waktu_mulai"]}, 1000.0]},
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "count": {"$sum": 1},
                "avg_batch_mlt": {"$avg": "$batch_mlt"},
            }
        },
    ]

    res_botol = await db.botol.aggregate(pipeline_botol).to_list(1)
    res_batch = await db.batch.aggregate(pipeline_batch).to_list(1)

    avg_unit_mlt = round(float(res_botol[0].get("avg_unit_mlt") or 0.0), 3) if res_botol else 0.0
    avg_durasi_isi = round(float(res_botol[0].get("avg_durasi_isi") or 0.0), 3) if res_botol else 0.0
    tot_botol = int(res_botol[0].get("count") or 0) if res_botol else 0

    avg_batch_mlt = round(float(res_batch[0].get("avg_batch_mlt") or 0.0), 3) if res_batch else 0.0
    tot_batch = int(res_batch[0].get("count") or 0) if res_batch else 0

    return LeadTimeResponse(
        mesin_id=clean_id,
        unit_mlt_avg_detik=avg_unit_mlt,
        batch_mlt_avg_detik=avg_batch_mlt,
        durasi_isi_avg_detik=avg_durasi_isi,
        total_botol_dianalisis=tot_botol,
        total_batch_dianalisis=tot_batch,
    )


@router.get(
    "/{id}/reliability",
    response_model=ReliabilityResponse,
    summary="Ambil metrik reliabilitas mesin: MTBF, MTTR, dan frekuensi breakdown",
    tags=["Analitik MES & Laporan"],
)
async def ambil_reliabilitas(
    id: str,
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    pengguna: Optional[str] = Query(None, description="Filter berdasarkan pengguna"),
    dari: Optional[str] = Query(None, description="Awal rentang waktu (ISO 8601 UTC)"),
    sampai: Optional[str] = Query(None, description="Akhir rentang waktu (ISO 8601 UTC)"),
    _: Optional[str] = Depends(verify_read_access),
    settings: Settings = Depends(get_settings),
):
    """Menghitung Mean Time Between Failures (MTBF) dan Mean Time to Repair (MTTR)."""
    db = get_db()
    clean_id = id.strip()

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

    # 1. Hitung durasi dan jumlah kejadian darurat dari event E-stop
    estop_tekan_jenis = settings.EVENT_JENIS_ESTOP_TEKAN
    estop_lepas_jenis = settings.EVENT_JENIS_ESTOP_LEPAS

    match_event: Dict[str, Any] = {
        "mesin_id": clean_id,
        "jenis": {"$in": [estop_tekan_jenis, estop_lepas_jenis]},
    }
    if sesi_id:
        match_event["sesi_id"] = sesi_id.strip()
    if pengguna:
        match_event["pengguna"] = pengguna.strip().lower()

    events = await db.event.find(match_event).sort([("sesi_id", 1), ("waktu", 1)]).to_list(None)
    total_downtime, jumlah_kejadian, _, _ = _hitung_downtime_dan_kejadian(
        events, dt_dari, dt_sampai, estop_tekan_jenis, estop_lepas_jenis
    )

    # 2. Hitung total operating time dari batch
    match_batch: Dict[str, Any] = {"mesin_id": clean_id}
    if sesi_id:
        match_batch["sesi_id"] = sesi_id.strip()
    if pengguna:
        match_batch["pengguna"] = pengguna.strip().lower()
    if dt_dari or dt_sampai:
        tf: Dict[str, Any] = {}
        if dt_dari:
            tf["$gte"] = dt_dari
        if dt_sampai:
            tf["$lte"] = dt_sampai
        match_batch["waktu_selesai"] = tf

    res_batch = await db.batch.aggregate([
        {"$match": match_batch},
        {"$group": {"_id": None, "total_op_time": {"$sum": "$production_time"}}},
    ]).to_list(1)

    total_op_time = float(res_batch[0].get("total_op_time", 0.0)) if res_batch else 0.0

    # Fallback jika belum ada batch: cari planned_production_time dari telemetri
    if total_op_time <= 0:
        match_tel: Dict[str, Any] = {"mesin_id": clean_id}
        if sesi_id:
            match_tel["sesi_id"] = sesi_id.strip()
        tel_doc = await db.telemetri.find_one(match_tel, sort=[("waktu", -1)])
        if tel_doc:
            planned = float(tel_doc.get("planned_production_time") or 0.0)
            total_op_time = max(0.0, planned - total_downtime)

    mtbf = calculate_mtbf(total_op_time, jumlah_kejadian)
    mttr = calculate_mttr(total_downtime, jumlah_kejadian)

    return ReliabilityResponse(
        mesin_id=clean_id,
        mtbf_detik=mtbf,
        mttr_detik=mttr,
        jumlah_breakdown=jumlah_kejadian,
        total_operating_time_detik=round(total_op_time, 3),
        total_downtime_detik=round(total_downtime, 3),
    )


@router.get(
    "/{id}/inventori",
    response_model=InventoriResponse,
    summary="Ambil status inventori bahan baku (stok rak atas dan restock)",
    tags=["Analitik MES & Laporan"],
)
async def ambil_inventori_mesin(
    id: str,
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    _: Optional[str] = Depends(verify_read_access),
):
    """Membaca status sisa stok rak atas, kapasitas rak, jumlah restock, dan indikator butuh restock."""
    db = get_db()
    clean_id = id.strip()
    query: Dict[str, Any] = {"mesin_id": clean_id}
    if sesi_id:
        query["sesi_id"] = sesi_id.strip()

    doc = await db.telemetri.find_one(query, sort=[("waktu", -1)])
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data telemetri inventori untuk mesin '{id}' belum tersedia",
        )

    sisa = int(doc.get("sisa_stok_rak_atas") or 0)
    kapasitas = int(doc.get("kapasitas_stok_rak_atas") or 100)
    jml_restock = int(doc.get("jumlah_restock") or 0)
    jml_auto = int(doc.get("jumlah_auto_replenish_rak") or 0)

    pct = round((sisa / kapasitas) * 100.0, 2) if kapasitas > 0 else 0.0
    butuh = pct <= 20.0

    return InventoriResponse(
        mesin_id=clean_id,
        sisa_stok_rak_atas=sisa,
        kapasitas_stok_rak_atas=kapasitas,
        jumlah_restock=jml_restock,
        jumlah_auto_replenish_rak=jml_auto,
        persentase_stok=pct,
        butuh_restock=butuh,
    )


@router.get(
    "/{id}/kapasitas",
    response_model=KapasitasResponse,
    summary="Ambil analisis kapasitas produksi teoritis vs efektif",
    tags=["Analitik MES & Laporan"],
)
async def ambil_kapasitas_mesin(
    id: str,
    batch_ke: Optional[int] = Query(None, ge=1, description="Nomor batch tertentu"),
    sesi_id: Optional[str] = Query(None, description="Filter berdasarkan ID sesi"),
    _: Optional[str] = Depends(verify_read_access),
    settings: Settings = Depends(get_settings),
):
    """Menghitung kapasitas teoritis per jam, kapasitas efektif aktual, dan utilisasi kapasitas."""
    db = get_db()
    clean_id = id.strip()

    mesin_doc = await db.mesin.find_one({"_id": clean_id})
    ideal_ct = (mesin_doc.get("ideal_cycle_time") if mesin_doc else None) or settings.IDEAL_CYCLE_TIME
    kap_teoritis = calculate_theoretical_capacity(ideal_ct)

    query_batch: Dict[str, Any] = {"mesin_id": clean_id}
    if batch_ke is not None:
        query_batch["batch_ke"] = batch_ke
    if sesi_id:
        query_batch["sesi_id"] = sesi_id.strip()

    batch_doc = await db.batch.find_one(query_batch, sort=[("batch_ke", -1), ("waktu_selesai", -1)])

    if batch_doc:
        act_ct = float(batch_doc.get("actual_cycle_time_avg") or ideal_ct)
        eff_cap = float(batch_doc.get("effective_capacity_per_hour") or 0.0)
    else:
        # Fallback telemetri
        query_tel: Dict[str, Any] = {"mesin_id": clean_id}
        if sesi_id:
            query_tel["sesi_id"] = sesi_id.strip()
        tel_doc = await db.telemetri.find_one(query_tel, sort=[("waktu", -1)])
        if tel_doc:
            act_ct = float(tel_doc.get("actual_cycle_time_avg") or ideal_ct)
            eff_cap = float(tel_doc.get("production_capacity_per_hour") or calculate_effective_capacity_per_hour(int(tel_doc.get("botol_selesai") or 0), float(tel_doc.get("planned_production_time") or 3600)))
        else:
            act_ct = ideal_ct
            eff_cap = 0.0

    utilisasi = round((eff_cap / kap_teoritis) * 100.0, 2) if kap_teoritis > 0 else 0.0

    return KapasitasResponse(
        mesin_id=clean_id,
        kapasitas_teoritis_per_jam=kap_teoritis,
        kapasitas_efektif_per_jam=eff_cap,
        utilisasi_kapasitas_pct=utilisasi,
        actual_cycle_time_avg=act_ct,
        ideal_cycle_time=ideal_ct,
    )
