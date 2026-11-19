"""Skema dan model Pydantic v2 untuk validasi data mesin pengisi botol."""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional, Union
import dateutil.parser
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.config import get_settings


def parse_iso8601_utc(v: Any) -> datetime:
    """Memvalidasi dan mengonversi timestamp ISO 8601 menjadi datetime tz-aware UTC.

    Menolak timestamp naive tanpa informasi zona waktu.
    """
    if isinstance(v, str):
        try:
            v = dateutil.parser.isoparse(v.strip())
        except (ValueError, OverflowError) as e:
            raise ValueError(
                f"Format timestamp ISO 8601 tidak valid: {e}. Contoh yang benar: '2026-10-29T10:00:00Z'"
            )
    if not isinstance(v, datetime):
        raise ValueError("Timestamp harus berupa string ISO 8601 atau objek datetime tz-aware")
    if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
        raise ValueError(
            "Timestamp harus menyertakan zona waktu (UTC), contoh: '2026-10-29T10:00:00Z'"
        )
    return v.astimezone(timezone.utc)


def parse_optional_iso8601_utc(v: Any) -> Optional[datetime]:
    if not v:
        return None
    return parse_iso8601_utc(v)


def validate_and_normalize_pengguna(v: Any) -> str:
    """Memvalidasi dan menormalisasi nama pengguna ke huruf kecil."""
    if not isinstance(v, str) or not v.strip():
        raise ValueError("Field 'pengguna' wajib diisi string tidak kosong")
    normalized = v.strip().lower()
    settings = get_settings()
    if normalized not in settings.pengguna_valid_set:
        valid_list_str = ", ".join(settings.pengguna_valid_list)
        raise ValueError(
            f"Pengguna '{v}' tidak sah. Nilai yang diperbolehkan: {valid_list_str}"
        )
    return normalized


UtcDatetime = Annotated[datetime, BeforeValidator(parse_iso8601_utc)]
OptionalUtcDatetime = Annotated[Optional[datetime], BeforeValidator(parse_optional_iso8601_utc)]
PenggunaStr = Annotated[str, BeforeValidator(validate_and_normalize_pengguna)]


class ModeEnum(str, Enum):
    MATI = "Mati"
    SIAP = "Siap"
    BERJALAN = "Berjalan"
    DARURAT = "Darurat"


class SumberEnum(str, Enum):
    PEMAIN = "pemain"
    SISTEM = "sistem"
    OPERATOR = "operator"
    ESP32 = "esp32"


class StatusBotolEnum(str, Enum):
    OK = "OK"
    TIDAK_PENUH = "TIDAK_PENUH"
    TANPA_TUTUP = "TANPA_TUTUP"


class OperatorModeEnum(str, Enum):
    SETUP = "Setup"
    INFEED = "Infeed"
    PACKAGING = "Packaging"
    RESTOCK = "Restock"


class KategoriDowntimeEnum(str, Enum):
    UNPLANNED_BREAKDOWN = "UNPLANNED_BREAKDOWN"
    PLANNED_SETUP = "PLANNED_SETUP"
    BLOCKED_FULL_BIN = "BLOCKED_FULL_BIN"
    POWER_OFF = "POWER_OFF"
    NORMAL_RUN = "NORMAL_RUN"


class MCBModel(BaseModel):
    utama: bool = Field(..., description="Status MCB Utama")
    mesin: bool = Field(..., description="Status MCB Mesin")
    kontrol: bool = Field(..., description="Status MCB Kontrol")
    lampu: bool = Field(..., description="Status MCB Lampu")

    model_config = ConfigDict(extra="allow")


class GPIOModel(BaseModel):
    step: Optional[Union[bool, int]] = None
    dir: Optional[Union[bool, int]] = None
    en: Optional[Union[bool, int]] = None
    pompa: Optional[Union[bool, int]] = None
    buzzer: Optional[Union[bool, int]] = None
    ir: Optional[Union[bool, int]] = None
    start: Optional[Union[bool, int]] = None
    limit: Optional[Union[bool, int]] = None

    model_config = ConfigDict(extra="allow")


# ============================================================================
# Model Tulis (Payload dari pengirim)
# ============================================================================

class TelemetriCreate(BaseModel):
    # Identitas
    waktu: UtcDatetime = Field(..., description="Timestamp ISO 8601 UTC dari pengirim")
    mesin_id: str = Field(..., min_length=1, description="ID mesin, mis. mesin-01")
    sesi_id: str = Field(..., min_length=1, description="ID sesi play/produksi")
    pengguna: PenggunaStr = Field(..., description="Identitas pengguna (mis. gibral, haikal, alvin, naya)")
    id_kirim: Optional[str] = Field(None, description="ID unik pengiriman untuk idempotensi/dedup")

    # Status Operasi & Operator
    mode: Optional[Union[ModeEnum, str]] = Field(None, description="Mode operasi mesin (Mati/Siap/Berjalan/Darurat)")
    darurat: Optional[bool] = Field(False, description="Status tombol darurat / E-stop aktif")
    tahap: Optional[Union[str, int]] = Field(None, description="Tahap proses mesin (misal 'Mengisi + Memasang tutup' atau integer)")
    operator_tugas: Optional[str] = Field(None, description="Tugas operator yang sedang berlangsung")
    batch_ke: Optional[int] = Field(None, description="Nomor urut batch yang sedang berjalan")
    operator_mode: Optional[Union[OperatorModeEnum, str]] = Field(None, description="Mode kerja operator")
    setup_selesai: Optional[bool] = Field(None, description="Apakah setup mesin sudah selesai")
    batch_completed: Optional[bool] = Field(None, description="Apakah batch saat ini telah selesai")
    sedang_starving: Optional[bool] = Field(None, description="Apakah mesin sedang starving (kehabisan botol kosong)")
    status_qc_terakhir: Optional[str] = Field(None, description="Status QC botol terakhir keluar (OK / Reject_*)")

    # Output Produksi & Kualitas
    botol_selesai: Optional[int] = Field(None, ge=0, description="Total botol yang selesai diproses")
    botol_ok: Optional[int] = Field(None, ge=0, description="Jumlah botol berstatus OK")
    botol_reject: Optional[int] = Field(None, ge=0, description="Jumlah botol reject/cacat")
    reject_isi_kurang: Optional[int] = Field(None, ge=0, description="Jumlah botol reject karena isi kurang")
    reject_tanpa_tutup: Optional[int] = Field(None, ge=0, description="Jumlah botol reject tanpa tutup")
    total_dikemas: Optional[int] = Field(None, ge=0, description="Total botol yang sudah dikemas ke kardus")
    kardus_selesai: Optional[int] = Field(None, ge=0, description="Total kardus berisi penuh")
    first_pass_yield: Optional[float] = Field(None, description="First Pass Yield (rasio 0.0-1.0 atau persen)")

    # Work-in-Process (WIP)
    sisa_peti: Optional[int] = Field(None, ge=0, description="Sisa botol kosong di peti infeed")
    wip_turret: Optional[int] = Field(None, ge=0, description="Jumlah botol yang sedang berada di turret")
    isi_kotak: Optional[int] = Field(None, ge=0, description="Jumlah botol di kotak penampung OK")
    isi_kotak_reject: Optional[int] = Field(None, ge=0, description="Jumlah botol di kotak reject")
    wip_total: Optional[int] = Field(None, ge=0, description="Total botol dalam proses")

    # Inventori & Restock
    sisa_stok_rak_atas: Optional[int] = Field(None, ge=0, description="Sisa stok botol di rak atas")
    kapasitas_stok_rak_atas: Optional[int] = Field(None, ge=0, description="Kapasitas rak atas botol")
    jumlah_restock: Optional[int] = Field(None, ge=0, description="Jumlah kali operator melakukan restock manual")
    jumlah_auto_replenish_rak: Optional[int] = Field(None, ge=0, description="Jumlah kali auto-replenish rak")

    # Waktu Kumulatif (detik)
    setup_time: Optional[float] = Field(None, ge=0.0, description="Waktu kumulatif setup mesin")
    batch_cycle_time: Optional[float] = Field(None, ge=0.0, description="Waktu kumulatif siklus batch")
    starvation_downtime: Optional[float] = Field(None, ge=0.0, description="Waktu kumulatif terhenti karena starvation")
    planned_production_time: Optional[float] = Field(None, ge=0.0, description="Waktu produksi yang direncanakan")
    production_time: Optional[float] = Field(None, ge=0.0, description="Waktu produksi aktual (Operating Time)")
    downtime_unplanned: Optional[float] = Field(None, ge=0.0, description="Total durasi downtime tak terencana")
    packaging_time: Optional[float] = Field(None, ge=0.0, description="Waktu proses packaging")

    # Cycle Time & Kapasitas
    actual_cycle_time_avg: Optional[float] = Field(None, ge=0.0, description="Rata-rata cycle time aktual per botol")
    ideal_cycle_time: Optional[float] = Field(4.1, ge=0.0, description="Cycle time ideal mesin (detik)")
    production_capacity_per_hour: Optional[float] = Field(878.05, ge=0.0, description="Kapasitas produksi teoritis per jam")
    kapasitas_peti: Optional[int] = Field(30, ge=0, description="Kapasitas botol di peti")
    kapasitas_slot_turret: Optional[int] = Field(10, ge=0, description="Kapasitas slot pada turret")
    kapasitas_kotak_ok: Optional[int] = Field(30, ge=0, description="Kapasitas kotak penampung OK")
    kapasitas_kotak_reject: Optional[int] = Field(12, ge=0, description="Kapasitas kotak penampung reject")

    # Hardware legacy & toleransi extra
    mcb: Optional[Union[MCBModel, Dict[str, Any]]] = Field(None, description="Status sakelar MCB")
    gpio: Optional[Union[GPIOModel, Dict[str, Any]]] = Field(None, description="Status 8 pin GPIO")
    langkah: Optional[Union[str, int]] = Field(None, description="Langkah siklus saat ini")
    sudut_turret_deg: Optional[Union[float, int]] = Field(0.0, description="Posisi sudut turret dalam derajat")

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def validate_telemetri_counts(self) -> "TelemetriCreate":
        if self.botol_ok is not None and self.botol_reject is not None:
            expected = self.botol_ok + self.botol_reject
            if self.botol_selesai is not None and self.botol_selesai != expected:
                raise ValueError(
                    f"botol_selesai ({self.botol_selesai}) harus sama dengan botol_ok ({self.botol_ok}) + botol_reject ({self.botol_reject}) = {expected}"
                )
        if self.wip_total is None:
            if self.sisa_peti is not None or self.wip_turret is not None or self.isi_kotak is not None:
                self.wip_total = (self.sisa_peti or 0) + (self.wip_turret or 0) + (self.isi_kotak or 0)
        return self


class EventCreate(BaseModel):
    waktu: UtcDatetime = Field(..., description="Waktu kejadian ISO 8601 UTC")
    mesin_id: str = Field(..., min_length=1, description="ID mesin")
    sesi_id: str = Field(..., min_length=1, description="ID sesi")
    pengguna: PenggunaStr = Field(..., description="Identitas pengguna")
    id_kirim: Optional[str] = Field(None, description="ID unik pengiriman untuk dedup")
    jenis: str = Field(..., min_length=1, description="Nama kejadian, mis. estop_tekan, START, batch_mulai, dll.")
    mode_sebelum: Optional[Union[ModeEnum, str]] = Field(None, description="Mode mesin sebelum kejadian")
    mode_sesudah: Optional[Union[ModeEnum, str]] = Field(None, description="Mode mesin sesudah kejadian")
    pesan: Optional[str] = Field(None, description="Pesan deskriptif tambahan")
    sumber: SumberEnum = Field(..., description="Sumber kejadian (pemain/sistem/operator/esp32)")
    kategori_downtime: Optional[Union[KategoriDowntimeEnum, str]] = Field(None, description="Kategori downtime (UNPLANNED_BREAKDOWN, PLANNED_SETUP, dll.)")
    batch_ke: Optional[int] = Field(None, ge=1, description="Nomor urut batch jika terkait batch")
    detail: Optional[Dict[str, Any]] = Field(None, description="Data detail tambahan kejadian")

    model_config = ConfigDict(extra="allow")


class BotolCreate(BaseModel):
    mesin_id: str = Field(..., min_length=1, description="ID mesin")
    sesi_id: str = Field(..., min_length=1, description="ID sesi")
    pengguna: PenggunaStr = Field(..., description="Identitas pengguna")
    id_kirim: Optional[str] = Field(None, description="ID unik pengiriman untuk dedup")
    nomor: int = Field(..., ge=1, description="Nomor urut botol")
    slot: int = Field(..., ge=0, description="Nomor slot turret tempat botol berada")
    waktu_masuk: UtcDatetime = Field(..., description="Waktu botol masuk slot")
    waktu_isi_mulai: OptionalUtcDatetime = Field(None, description="Waktu mulai pengisian")
    waktu_isi_selesai: OptionalUtcDatetime = Field(None, description="Waktu selesai pengisian")
    waktu_tutup: OptionalUtcDatetime = Field(None, description="Waktu pemasangan tutup botol")
    waktu_keluar: UtcDatetime = Field(..., description="Waktu botol jatuh ke kotak")
    level_isi: float = Field(..., ge=0.0, le=1.0, description="Level isi cairan 0.0 - 1.0")
    bertutup: bool = Field(..., description="Status apakah botol bertutup")
    status: StatusBotolEnum = Field(..., description="Status botol (OK, TIDAK_PENUH, TANPA_TUTUP)")
    batch_ke: Optional[int] = Field(None, ge=1, description="Nomor urut batch")
    durasi_isi_detik: Optional[float] = Field(None, ge=0.0, description="Durasi pengisian cairan (detik)")
    unit_mlt_detik: Optional[float] = Field(None, ge=0.0, description="Manufacturing Lead Time per unit botol (detik)")

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def validate_botol_ordering_and_durations(self) -> "BotolCreate":
        # Validasi urutan waktu menaik: waktu_masuk <= waktu_isi_mulai <= waktu_isi_selesai <= waktu_tutup <= waktu_keluar
        ordered_fields = [
            ("waktu_masuk", self.waktu_masuk),
            ("waktu_isi_mulai", self.waktu_isi_mulai),
            ("waktu_isi_selesai", self.waktu_isi_selesai),
            ("waktu_tutup", self.waktu_tutup),
            ("waktu_keluar", self.waktu_keluar),
        ]
        present = [(name, dt) for name, dt in ordered_fields if dt is not None]
        for i in range(len(present) - 1):
            if present[i][1] > present[i + 1][1]:
                raise ValueError(
                    f"Urutan timestamp botol harus menaik: '{present[i][0]}' ({present[i][1].isoformat()}) "
                    f"tidak boleh melebihi '{present[i+1][0]}' ({present[i+1][1].isoformat()})"
                )

        if self.durasi_isi_detik is None and self.waktu_isi_selesai and self.waktu_isi_mulai:
            self.durasi_isi_detik = round((self.waktu_isi_selesai - self.waktu_isi_mulai).total_seconds(), 3)

        if self.unit_mlt_detik is None and self.waktu_keluar and self.waktu_masuk:
            self.unit_mlt_detik = round((self.waktu_keluar - self.waktu_masuk).total_seconds(), 3)

        return self


class BatchCreate(BaseModel):
    mesin_id: str = Field(..., min_length=1, description="ID mesin")
    sesi_id: str = Field(..., min_length=1, description="ID sesi")
    pengguna: PenggunaStr = Field(..., description="Identitas pengguna")
    id_kirim: Optional[str] = Field(None, description="ID unik pengiriman untuk dedup")
    batch_ke: int = Field(..., ge=1, description="Nomor urut batch")
    waktu_mulai: UtcDatetime = Field(..., description="Waktu mulai batch")
    waktu_selesai: UtcDatetime = Field(..., description="Waktu selesai batch")
    target_qty: int = Field(..., ge=0, description="Target jumlah botol dalam 1 batch")
    botol_selesai: int = Field(..., ge=0, description="Jumlah total botol yang selesai")
    botol_ok: int = Field(..., ge=0, description="Jumlah botol berstatus OK")
    botol_reject: int = Field(..., ge=0, description="Jumlah botol reject")
    reject_isi_kurang: Optional[int] = Field(0, ge=0, description="Jumlah reject akibat isi kurang")
    reject_tanpa_tutup: Optional[int] = Field(0, ge=0, description="Jumlah reject akibat tanpa tutup")
    total_dikemas: Optional[int] = Field(0, ge=0, description="Total botol dikemas ke kardus")

    # Waktu kumulatif produksi (detik)
    planned_production_time: float = Field(..., ge=0.0, description="Planned Production Time (detik)")
    production_time: Optional[float] = Field(None, ge=0.0, description="Operating / Production Time (detik)")
    setup_time: Optional[float] = Field(0.0, ge=0.0, description="Waktu setup (detik)")
    starvation_downtime: Optional[float] = Field(0.0, ge=0.0, description="Downtime akibat kehabisan infeed (detik)")
    downtime_unplanned: Optional[float] = Field(0.0, ge=0.0, description="Downtime darurat tak terencana (detik)")
    packaging_time: Optional[float] = Field(0.0, ge=0.0, description="Waktu packaging kardus (detik)")
    mlt_batch: Optional[float] = Field(None, ge=0.0, description="Manufacturing Lead Time batch (detik)")

    # Kapasitas & Metrik KPI dari Unity
    ideal_cycle_time: Optional[float] = Field(4.1, ge=0.0, description="Cycle time ideal mesin (detik)")
    actual_cycle_time_avg: Optional[float] = Field(None, ge=0.0, description="Rata-rata cycle time aktual per botol")
    effective_capacity_per_hour: Optional[float] = Field(None, ge=0.0, description="Kapasitas efektif (botol/jam)")
    availability_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Availability dalam persen (%)")
    performance_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Performance dalam persen (%)")
    quality_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Quality dalam persen (%)")
    oee_pct: Optional[float] = Field(None, ge=0.0, le=100.0, description="Overall Equipment Effectiveness dalam persen (%)")

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def validate_batch(self) -> "BatchCreate":
        if self.waktu_mulai > self.waktu_selesai:
            raise ValueError(
                f"waktu_mulai ({self.waktu_mulai.isoformat()}) tidak boleh lebih besar dari "
                f"waktu_selesai ({self.waktu_selesai.isoformat()})"
            )
        if self.botol_selesai != (self.botol_ok + self.botol_reject):
            raise ValueError(
                f"botol_selesai ({self.botol_selesai}) harus sama dengan botol_ok ({self.botol_ok}) + botol_reject ({self.botol_reject})"
            )
        return self


# ============================================================================
# Model Respons API
# ============================================================================

class TelemetriResponse(BaseModel):
    status: str = "sukses"
    pesan: str
    tersimpan: int
    duplikat_diabaikan: int


class WriteSingleResponse(BaseModel):
    status: str = "sukses"
    pesan: str
    id_kirim: Optional[str] = None
    tersimpan: bool
    id: Optional[str] = None


class RingkasanStatistik(BaseModel):
    jumlah_botol: int
    botol_gagal: int
    rata_rata_waktu_siklus_detik: float
    total_durasi_darurat_detik: float
    botol_ok: int = 0
    kategori_kegagalan: Dict[str, int] = Field(default_factory=dict)


class RingkasanResponse(BaseModel):
    mesin_id: str
    sesi_id: Optional[str] = None
    pengguna: Optional[str] = None
    rentang: Dict[str, Optional[str]]
    jumlah_botol: int
    botol_gagal: int
    rata_rata_waktu_siklus_detik: float
    total_durasi_darurat_detik: float
    botol_ok: int = 0
    kategori_kegagalan: Dict[str, int] = Field(default_factory=dict)
    rincian_pengguna: Optional[Dict[str, RingkasanStatistik]] = None


class KejadianDowntimeItem(BaseModel):
    sesi_id: Optional[str] = None
    pengguna: Optional[str] = None
    waktu_mulai: str
    waktu_selesai: Optional[str] = None
    durasi_detik: float
    status: str
    pesan: Optional[str] = None


class DowntimeResponse(BaseModel):
    mesin_id: str
    rentang: Dict[str, Optional[str]]
    total_durasi_downtime_detik: float
    jumlah_kejadian_downtime: int
    kejadian: List[KejadianDowntimeItem]
    rincian_pengguna: Optional[Dict[str, float]] = None


class LaporanProduksiSection(BaseModel):
    total_botol: int
    rata_rata_waktu_siklus_detik: float
    total_waktu_siklus_detik: float


class LaporanKualitasSection(BaseModel):
    botol_ok: int
    botol_gagal: int
    persentase_ok: float
    kategori_kegagalan: Dict[str, int]


class LaporanDowntimeSection(BaseModel):
    total_durasi_detik: float
    jumlah_kejadian: int


class LaporanResponse(BaseModel):
    mesin_id: str
    rentang: Dict[str, Optional[str]]
    filter: Dict[str, Optional[str]]
    produksi: LaporanProduksiSection
    kualitas: LaporanKualitasSection
    downtime: LaporanDowntimeSection
    rincian_pengguna: Optional[Dict[str, Any]] = None


class OEEResponse(BaseModel):
    mesin_id: str
    sesi_id: Optional[str] = None
    batch_ke: Optional[int] = None
    availability: float
    performance: float
    quality: float
    oee: float
    availability_pct: float
    performance_pct: float
    quality_pct: float
    oee_pct: float
    losses: Dict[str, float]
    operating_time_detik: float
    planned_time_detik: float
    kpi_mismatch: Optional[bool] = None


class WIPResponse(BaseModel):
    mesin_id: str
    wip_total: int
    sisa_peti: int
    wip_turret: int
    isi_kotak: int
    isi_kotak_reject: int
    warning: bool
    kapasitas_maksimal: int
    waktu: Optional[str] = None


class KualitasAnalisisResponse(BaseModel):
    mesin_id: str
    total_botol: int
    botol_ok: int
    botol_reject: int
    first_pass_yield_pct: float
    pareto_reject: Dict[str, int]
    level_isi_stats: Dict[str, Any]


class LeadTimeResponse(BaseModel):
    mesin_id: str
    unit_mlt_avg_detik: float
    batch_mlt_avg_detik: float
    durasi_isi_avg_detik: float
    total_botol_dianalisis: int
    total_batch_dianalisis: int


class ReliabilityResponse(BaseModel):
    mesin_id: str
    mtbf_detik: Optional[float]
    mttr_detik: Optional[float]
    jumlah_breakdown: int
    total_operating_time_detik: float
    total_downtime_detik: float


class InventoriResponse(BaseModel):
    mesin_id: str
    sisa_stok_rak_atas: int
    kapasitas_stok_rak_atas: int
    jumlah_restock: int
    jumlah_auto_replenish_rak: int
    persentase_stok: float
    butuh_restock: bool


class KapasitasResponse(BaseModel):
    mesin_id: str
    kapasitas_teoritis_per_jam: float
    kapasitas_efektif_per_jam: float
    utilisasi_kapasitas_pct: float
    actual_cycle_time_avg: float
    ideal_cycle_time: float


class HealthResponse(BaseModel):
    status: str
    database: str
    waktu: str
    detail: Optional[str] = None
