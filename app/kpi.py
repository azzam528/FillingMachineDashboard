"""Modul murni untuk perhitungan KPI mesin, OEE, Six Big Losses, kapasitas, dan reliabilitas.

Semua fungsi di modul ini murni (pure functions tanpa akses database) dan aman dari pembagian dengan nol
(division by zero). Jika penyebut bernilai nol atau input tidak mencukupi, fungsi mengembalikan nilai aman
(0.0 atau None) sesuai dokumentasi masing-masing fungsi.
"""

import math
from typing import Any, Dict, List, Optional, Tuple


def calculate_production_time(
    planned_production_time: float,
    downtime_unplanned: float = 0.0,
    setup_time: float = 0.0,
    starvation_downtime: float = 0.0,
    packaging_time: float = 0.0,
) -> float:
    """Menghitung waktu produksi aktual (Operating Time).

    Rumus:
        production_time = planned_production_time - (downtime_unplanned + setup_time + starvation_downtime + packaging_time)

    Returns:
        float >= 0.0. Jika hasil negatif, dikembalikan 0.0.
    """
    total_losses = (downtime_unplanned or 0.0) + (setup_time or 0.0) + (starvation_downtime or 0.0) + (packaging_time or 0.0)
    prod_time = (planned_production_time or 0.0) - total_losses
    return round(max(0.0, prod_time), 3)


def calculate_availability(
    production_time: float,
    planned_production_time: float,
) -> float:
    """Menghitung Availability (rasio 0.0 - 1.0).

    Rumus:
        availability = production_time / planned_production_time

    Returns:
        float dalam rentang [0.0, 1.0]. Jika planned_production_time <= 0, mengembalikan 0.0.
    """
    if not planned_production_time or planned_production_time <= 0:
        return 0.0
    val = (production_time or 0.0) / planned_production_time
    return round(max(0.0, min(1.0, val)), 6)


def calculate_performance(
    ideal_cycle_time: float,
    botol_selesai: int,
    production_time: float,
) -> float:
    """Menghitung Performance (rasio 0.0 - 1.0).

    Rumus:
        performance = (ideal_cycle_time * botol_selesai) / production_time

    Returns:
        float dalam rentang [0.0, 1.0]. Jika production_time <= 0, mengembalikan 0.0.
    """
    if not production_time or production_time <= 0:
        return 0.0
    val = ((ideal_cycle_time or 0.0) * (botol_selesai or 0)) / production_time
    return round(max(0.0, min(1.0, val)), 6)


def calculate_quality(
    botol_ok: int,
    botol_selesai: int,
) -> float:
    """Menghitung Quality / First Pass Yield (rasio 0.0 - 1.0).

    Rumus:
        quality = botol_ok / botol_selesai

    Returns:
        float dalam rentang [0.0, 1.0]. Jika botol_selesai <= 0, mengembalikan 0.0.
    """
    if not botol_selesai or botol_selesai <= 0:
        return 0.0
    val = (botol_ok or 0) / botol_selesai
    return round(max(0.0, min(1.0, val)), 6)


def calculate_oee(
    availability: float,
    performance: float,
    quality: float,
) -> float:
    """Menghitung Overall Equipment Effectiveness (OEE) (rasio 0.0 - 1.0).

    Rumus:
        oee = availability * performance * quality

    Returns:
        float dalam rentang [0.0, 1.0].
    """
    val = (availability or 0.0) * (performance or 0.0) * (quality or 0.0)
    return round(max(0.0, min(1.0, val)), 6)


def calculate_actual_cycle_time_avg(
    production_time: float,
    botol_selesai: int,
) -> float:
    """Menghitung rata-rata cycle time aktual per botol (detik/botol).

    Rumus:
        actual_cycle_time_avg = production_time / botol_selesai

    Returns:
        float detik. Jika botol_selesai <= 0, mengembalikan 0.0.
    """
    if not botol_selesai or botol_selesai <= 0:
        return 0.0
    return round((production_time or 0.0) / botol_selesai, 3)


def calculate_effective_capacity_per_hour(
    botol_selesai: int,
    mlt_batch_or_cycle_time: float,
) -> float:
    """Menghitung kapasitas efektif per jam (botol/jam).

    Rumus:
        effective_capacity_per_hour = (botol_selesai / mlt_batch) * 3600

    Returns:
        float botol/jam. Jika mlt_batch <= 0, mengembalikan 0.0.
    """
    if not mlt_batch_or_cycle_time or mlt_batch_or_cycle_time <= 0:
        return 0.0
    return round(((botol_selesai or 0) / mlt_batch_or_cycle_time) * 3600.0, 2)


def calculate_theoretical_capacity(
    ideal_cycle_time: float = 4.1,
) -> float:
    """Menghitung kapasitas teoritis maksimum (botol/jam).

    Rumus:
        theoretical_capacity = 3600 / ideal_cycle_time

    Returns:
        float botol/jam. Contoh untuk ideal 4.1s = 878.05 botol/jam.
    """
    if not ideal_cycle_time or ideal_cycle_time <= 0:
        return 0.0
    return round(3600.0 / ideal_cycle_time, 2)


def calculate_wip_total(
    sisa_peti: int,
    wip_turret: int,
    isi_kotak: int,
) -> int:
    """Menghitung total Work-in-Process (WIP).

    Rumus:
        wip_total = sisa_peti + wip_turret + isi_kotak
    Catatan: isi_kotak_reject dilaporkan terpisah.
    """
    return (sisa_peti or 0) + (wip_turret or 0) + (isi_kotak or 0)


def calculate_six_big_losses(
    downtime_unplanned: float,
    setup_time: float,
    starvation_downtime: float,
    packaging_time: float,
    production_time: float,
    ideal_cycle_time: float,
    botol_selesai: int,
    botol_reject: int,
) -> Dict[str, float]:
    """Menghitung rincian Six Big Losses dalam satuan detik.

    1. Equipment Failure / Breakdown: downtime_unplanned
    2. Setup & Adjustments: setup_time
    3. Idling & Minor Stops / Starvation + Packaging: starvation_downtime + packaging_time
    4. Reduced Speed (Speed Loss): production_time - (ideal_cycle_time * botol_selesai)
    5. Process Defects (Quality Loss): botol_reject * ideal_cycle_time
    6. Startup Rejects: dimasukkan ke quality loss bila ada
    """
    unplanned = round(max(0.0, downtime_unplanned or 0.0), 3)
    setup = round(max(0.0, setup_time or 0.0), 3)
    starvation = round(max(0.0, starvation_downtime or 0.0), 3)
    packaging = round(max(0.0, packaging_time or 0.0), 3)

    speed_loss = round(max(0.0, (production_time or 0.0) - ((ideal_cycle_time or 0.0) * (botol_selesai or 0))), 3)
    quality_loss = round(max(0.0, (botol_reject or 0) * (ideal_cycle_time or 0.0)), 3)

    return {
        "breakdown": unplanned,
        "setup": setup,
        "starving_packaging": round(starvation + packaging, 3),
        "starvation": starvation,
        "packaging": packaging,
        "speed_loss": speed_loss,
        "quality_loss": quality_loss,
    }


def calculate_mtbf(
    production_time: float,
    jumlah_breakdown: int,
) -> Optional[float]:
    """Menghitung Mean Time Between Failures (MTBF) dalam detik.

    Rumus:
        MTBF = production_time / jumlah_breakdown

    Returns:
        float detik, atau None jika jumlah_breakdown == 0 (tidak ada kegagalan).
    """
    if not jumlah_breakdown or jumlah_breakdown <= 0:
        return None
    return round((production_time or 0.0) / jumlah_breakdown, 3)


def calculate_mttr(
    downtime_unplanned: float,
    jumlah_breakdown: int,
) -> Optional[float]:
    """Menghitung Mean Time to Repair (MTTR) dalam detik.

    Rumus:
        MTTR = downtime_unplanned / jumlah_breakdown

    Returns:
        float detik, atau None jika jumlah_breakdown == 0 (tidak ada kegagalan).
    """
    if not jumlah_breakdown or jumlah_breakdown <= 0:
        return None
    return round((downtime_unplanned or 0.0) / jumlah_breakdown, 3)


def calculate_level_isi_stats(
    levels: List[float],
    batas_lulus_qc: float = 0.85,
) -> Dict[str, Any]:
    """Menghitung statistik deskriptif untuk level isi cairan (mean, std, min, max, UCL/LCL, defect count).

    UCL = mean + 3*std
    LCL = max(0.0, mean - 3*std)
    """
    if not levels:
        return {
            "count": 0,
            "mean": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
            "ucl": 0.0,
            "lcl": 0.0,
            "jumlah_kurang_dari_batas": 0,
            "batas_lulus_qc": batas_lulus_qc,
            "total_cairan": 0.0,
        }

    n = len(levels)
    mean_val = sum(levels) / n
    variance = sum((x - mean_val) ** 2 for x in levels) / n if n > 0 else 0.0
    std_val = math.sqrt(variance)
    min_val = min(levels)
    max_val = max(levels)
    ucl = min(1.0, mean_val + (3.0 * std_val))
    lcl = max(0.0, mean_val - (3.0 * std_val))
    kurang_batas = sum(1 for x in levels if x < batas_lulus_qc)
    total_cairan = sum(levels)

    return {
        "count": n,
        "mean": round(mean_val, 4),
        "std": round(std_val, 4),
        "min": round(min_val, 4),
        "max": round(max_val, 4),
        "ucl": round(ucl, 4),
        "lcl": round(lcl, 4),
        "jumlah_kurang_dari_batas": kurang_batas,
        "batas_lulus_qc": batas_lulus_qc,
        "total_cairan": round(total_cairan, 4),
    }


def evaluate_batch_kpis(
    planned_production_time: float,
    downtime_unplanned: float,
    setup_time: float,
    starvation_downtime: float,
    packaging_time: float,
    botol_selesai: int,
    botol_ok: int,
    ideal_cycle_time: float = 4.1,
    mlt_batch: Optional[float] = None,
    tolerance_pct: float = 0.5,
    unity_availability_pct: Optional[float] = None,
    unity_performance_pct: Optional[float] = None,
    unity_quality_pct: Optional[float] = None,
    unity_oee_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Menghitung ulang seluruh metrik batch dan mengevaluasi toleransi kpi_mismatch."""
    prod_time = calculate_production_time(
        planned_production_time=planned_production_time,
        downtime_unplanned=downtime_unplanned,
        setup_time=setup_time,
        starvation_downtime=starvation_downtime,
        packaging_time=packaging_time,
    )

    avail_ratio = calculate_availability(prod_time, planned_production_time)
    perf_ratio = calculate_performance(ideal_cycle_time, botol_selesai, prod_time)
    qual_ratio = calculate_quality(botol_ok, botol_selesai)
    oee_ratio = calculate_oee(avail_ratio, perf_ratio, qual_ratio)

    avail_pct = round(avail_ratio * 100.0, 2)
    perf_pct = round(perf_ratio * 100.0, 2)
    qual_pct = round(qual_ratio * 100.0, 2)
    oee_pct = round((oee_ratio * 100.0) + 1e-7, 2)

    actual_ct = calculate_actual_cycle_time_avg(prod_time, botol_selesai)
    eff_mlt = mlt_batch if (mlt_batch and mlt_batch > 0) else planned_production_time
    eff_cap = calculate_effective_capacity_per_hour(botol_selesai, eff_mlt)

    # Evaluasi kpi_mismatch terhadap laporan Unity
    mismatch = False
    checks = [
        (unity_availability_pct, avail_pct),
        (unity_performance_pct, perf_pct),
        (unity_quality_pct, qual_pct),
        (unity_oee_pct, oee_pct),
    ]
    for u_val, s_val in checks:
        if u_val is not None:
            if abs(u_val - s_val) > tolerance_pct:
                mismatch = True
                break

    return {
        "production_time": prod_time,
        "availability_pct": avail_pct,
        "performance_pct": perf_pct,
        "quality_pct": qual_pct,
        "oee_pct": oee_pct,
        "actual_cycle_time_avg": actual_ct,
        "effective_capacity_per_hour": eff_cap,
        "kpi_mismatch": mismatch,
    }
