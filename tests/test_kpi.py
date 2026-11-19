"""Unit test untuk modul app.kpi."""

import pytest
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
    evaluate_batch_kpis,
)


def test_golden_batch_kpi_values():
    """Uji nilai golden test sesuai skenario referensi spesifikasi Web MES.

    Input:
    - planned_production_time = 240 detik
    - downtime_unplanned = 20 detik
    - setup_time = 15 detik
    - starvation_downtime = 5 detik
    - packaging_time = 50 detik
    - botol_selesai = 30
    - botol_ok = 27
    - botol_reject = 3
    - ideal_cycle_time = 4.1 detik

    Output yang diharapkan:
    - production_time = 150.0 detik
    - availability = 62.50% (0.625)
    - performance = 82.00% (0.82)
    - quality = 90.00% (0.90)
    - oee = 46.13% (0.46125)
    - actual_cycle_time_avg = 5.0 detik
    - effective_capacity_per_hour = 450.0 botol/jam
    - kapasitas_teoritis = 878.05 botol/jam
    """
    prod_time = calculate_production_time(
        planned_production_time=240.0,
        downtime_unplanned=20.0,
        setup_time=15.0,
        starvation_downtime=5.0,
        packaging_time=50.0,
    )
    assert prod_time == 150.0

    avail = calculate_availability(prod_time, 240.0)
    assert round(avail * 100.0, 2) == 62.50

    perf = calculate_performance(4.1, 30, prod_time)
    assert round(perf * 100.0, 2) == 82.00

    qual = calculate_quality(27, 30)
    assert round(qual * 100.0, 2) == 90.00

    oee = calculate_oee(avail, perf, qual)
    assert round((oee * 100.0) + 1e-7, 2) == 46.13

    actual_ct = calculate_actual_cycle_time_avg(prod_time, 30)
    assert actual_ct == 5.0

    eff_cap = calculate_effective_capacity_per_hour(30, 240.0)
    assert eff_cap == 450.0

    theor_cap = calculate_theoretical_capacity(4.1)
    assert theor_cap == 878.05


def test_golden_wip_total():
    """Uji perhitungan total WIP (sisa_peti: 18, wip_turret: 6, isi_kotak: 5) -> 29."""
    wip = calculate_wip_total(sisa_peti=18, wip_turret=6, isi_kotak=5)
    assert wip == 29


def test_six_big_losses():
    """Uji rincian Six Big Losses."""
    losses = calculate_six_big_losses(
        downtime_unplanned=20.0,
        setup_time=15.0,
        starvation_downtime=5.0,
        packaging_time=50.0,
        production_time=150.0,
        ideal_cycle_time=4.1,
        botol_selesai=30,
        botol_reject=3,
    )
    assert losses["breakdown"] == 20.0
    assert losses["setup"] == 15.0
    assert losses["starvation"] == 5.0
    assert losses["packaging"] == 50.0
    assert losses["starving_packaging"] == 55.0
    # speed loss: 150 - (4.1 * 30) = 150 - 123 = 27.0
    assert losses["speed_loss"] == 27.0
    # quality loss: 3 * 4.1 = 12.3
    assert losses["quality_loss"] == 12.3


def test_zero_division_safety():
    """Semua fungsi aman dari ZeroDivisionError."""
    assert calculate_production_time(0.0) == 0.0
    assert calculate_availability(10.0, 0.0) == 0.0
    assert calculate_performance(4.1, 10, 0.0) == 0.0
    assert calculate_quality(5, 0) == 0.0
    assert calculate_oee(0.0, 0.0, 0.0) == 0.0
    assert calculate_actual_cycle_time_avg(100.0, 0) == 0.0
    assert calculate_effective_capacity_per_hour(50, 0.0) == 0.0
    assert calculate_theoretical_capacity(0.0) == 0.0
    assert calculate_mtbf(100.0, 0) is None
    assert calculate_mttr(50.0, 0) is None


def test_mtbf_and_mttr():
    """Uji MTBF dan MTTR saat ada kejadian breakdown."""
    mtbf = calculate_mtbf(production_time=300.0, jumlah_breakdown=2)
    assert mtbf == 150.0

    mttr = calculate_mttr(downtime_unplanned=40.0, jumlah_breakdown=2)
    assert mttr == 20.0


def test_level_isi_stats():
    """Uji statistik level isi cairan dan batas kontrol UCL/LCL."""
    empty_stats = calculate_level_isi_stats([])
    assert empty_stats["count"] == 0
    assert empty_stats["mean"] == 0.0

    levels = [0.88, 0.90, 0.85, 0.92, 0.84, 0.89]
    stats = calculate_level_isi_stats(levels, batas_lulus_qc=0.85)
    assert stats["count"] == 6
    assert stats["min"] == 0.84
    assert stats["max"] == 0.92
    assert stats["jumlah_kurang_dari_batas"] == 1  # 0.84 < 0.85
    assert stats["ucl"] >= stats["mean"]
    assert stats["lcl"] <= stats["mean"]


def test_evaluate_batch_kpis_mismatch_detection():
    """Uji deteksi kpi_mismatch jika selisih nilai > 0.5% point."""
    # Skenario 1: Sesuai (selisih <= 0.5)
    res_match = evaluate_batch_kpis(
        planned_production_time=240.0,
        downtime_unplanned=20.0,
        setup_time=15.0,
        starvation_downtime=5.0,
        packaging_time=50.0,
        botol_selesai=30,
        botol_ok=27,
        tolerance_pct=0.5,
        unity_availability_pct=62.50,
        unity_performance_pct=82.00,
        unity_quality_pct=90.00,
        unity_oee_pct=46.13,
    )
    assert res_match["kpi_mismatch"] is False
    assert res_match["availability_pct"] == 62.50
    assert res_match["performance_pct"] == 82.00
    assert res_match["quality_pct"] == 90.00
    assert res_match["oee_pct"] == 46.13

    # Skenario 2: Mismatch (selisih > 0.5 misal Unity mengirim OEE 50.0%)
    res_mismatch = evaluate_batch_kpis(
        planned_production_time=240.0,
        downtime_unplanned=20.0,
        setup_time=15.0,
        starvation_downtime=5.0,
        packaging_time=50.0,
        botol_selesai=30,
        botol_ok=27,
        tolerance_pct=0.5,
        unity_oee_pct=50.0,  # beda > 0.5 dari 46.13%
    )
    assert res_mismatch["kpi_mismatch"] is True
