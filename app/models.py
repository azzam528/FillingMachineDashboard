"""Skema dan model Pydantic v2 untuk validasi data mesin pengisi botol."""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional, Union
import dateutil.parser
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.config import get_settings


def parse_iso8601_utc(v: Any) -> datetime:
    """Memvalidasi dan mengonversi timestamp ISO 8601 menjadi datetime tz-aware UTC.

    Menolak timestamp naive tanpa informasi zona waktu.
    """
    if isinstance(v, datetime):
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError(
                "Timestamp harus menyertakan zona waktu (UTC), contoh: '2026-10-29T10:00:00Z'"
            )
        return v.astimezone(timezone.utc)
    if isinstance(v, str):
        v = v.strip()
        try:
            dt = dateutil.parser.isoparse(v)
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                raise ValueError(
                    "Timestamp harus menyertakan zona waktu (UTC), contoh: '2026-10-29T10:00:00Z'"
                )
            return dt.astimezone(timezone.utc)
        except (ValueError, OverflowError) as e:
            raise ValueError(
                f"Format timestamp ISO 8601 tidak valid: {str(e)}. Contoh yang benar: '2026-10-29T10:00:00Z'"
            )
    raise ValueError("Timestamp harus berupa string ISO 8601 atau objek datetime tz-aware")


def parse_optional_iso8601_utc(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    return parse_iso8601_utc(v)


def validate_and_normalize_pengguna(v: Any) -> str:
    """Memvalidasi dan menormalisasi nama pengguna ke huruf kecil."""
    if not isinstance(v, str) or not v.strip():
        raise ValueError("Field 'pengguna' wajib diisi string tidak kosong")
    normalized = v.strip().lower()
    valid_set = get_settings().pengguna_valid_set
    if normalized not in valid_set:
        valid_list_str = ", ".join(get_settings().pengguna_valid_list)
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
    waktu: UtcDatetime = Field(..., description="Timestamp ISO 8601 UTC dari pengirim")
    mesin_id: str = Field(..., min_length=1, description="ID mesin, mis. mesin-01")
    sesi_id: str = Field(..., min_length=1, description="ID sesi play/produksi")
    pengguna: PenggunaStr = Field(..., description="Identitas pengguna (mis. gibral, haikal, alvin, naya)")
    id_kirim: Optional[str] = Field(None, description="ID unik pengiriman untuk idempotensi/dedup")
    mode: Optional[ModeEnum] = Field(None, description="Mode operasi mesin (Mati/Siap/Berjalan/Darurat)")
    darurat: bool = Field(..., description="Status tombol darurat / E-stop aktif")
    mcb: MCBModel = Field(..., description="Status sakelar MCB")
    tahap: Optional[Union[str, int]] = Field(None, description="Tahap proses mesin")
    langkah: Optional[Union[str, int]] = Field(None, description="Langkah siklus saat ini")
    sudut_turret_deg: Union[float, int] = Field(..., description="Posisi sudut turret dalam derajat")
    botol_selesai: int = Field(..., ge=0, description="Total botol yang selesai diproses")
    isi_kotak: int = Field(..., ge=0, description="Jumlah botol di kotak penampung saat ini")
    sisa_peti: int = Field(..., ge=0, description="Sisa botol kosong di peti infeed")
    operator_tugas: Optional[str] = Field(None, description="Tugas operator yang sedang berlangsung")
    gpio: Union[GPIOModel, Dict[str, Any]] = Field(..., description="Status 8 pin GPIO")

    model_config = ConfigDict(extra="allow")


class EventCreate(BaseModel):
    waktu: UtcDatetime = Field(..., description="Waktu kejadian ISO 8601 UTC")
    mesin_id: str = Field(..., min_length=1, description="ID mesin")
    sesi_id: str = Field(..., min_length=1, description="ID sesi")
    pengguna: PenggunaStr = Field(..., description="Identitas pengguna")
    id_kirim: Optional[str] = Field(None, description="ID unik pengiriman untuk dedup")
    jenis: str = Field(..., min_length=1, description="Nama kejadian, mis. estop_tekan, START, dll.")
    mode_sebelum: Optional[ModeEnum] = Field(None, description="Mode mesin sebelum kejadian")
    mode_sesudah: Optional[ModeEnum] = Field(None, description="Mode mesin sesudah kejadian")
    pesan: Optional[str] = Field(None, description="Pesan deskriptif tambahan")
    sumber: SumberEnum = Field(..., description="Sumber kejadian (pemain/sistem/operator/esp32)")
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

    model_config = ConfigDict(extra="allow")


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


class RingkasanResponse(BaseModel):
    mesin_id: str
    sesi_id: Optional[str] = None
    pengguna: Optional[str] = None
    rentang: Dict[str, Optional[str]]
    jumlah_botol: int
    botol_gagal: int
    rata_rata_waktu_siklus_detik: float
    total_durasi_darurat_detik: float
    rincian_pengguna: Optional[Dict[str, RingkasanStatistik]] = None


class HealthResponse(BaseModel):
    status: str
    database: str
    waktu: str
    detail: Optional[str] = None
