"""Konfigurasi aplikasi menggunakan pydantic-settings."""

from functools import lru_cache
from typing import Dict
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # MongoDB Atlas Configuration
    # Catatan keamanan: Jangan pernah mencetak MONGODB_URI ke log
    MONGODB_URI: str = Field(
        default="mongodb://localhost:27017",
        description="Connection string MongoDB Atlas",
    )
    MONGODB_DB_NAME: str = Field(
        default="liquidfilling",
        description="Nama database MongoDB",
    )

    # API Key per mesin: format "mesin-01:kunci1,mesin-02:kunci2"
    MESIN_API_KEYS: str = Field(
        default="mesin-01:kunci1",
        description="Daftar pasangan mesin_id:api_key dipisahkan koma",
    )

    # Pengaturan endpoint baca
    REQUIRE_KEY_FOR_READ: bool = Field(
        default=False,
        description="Jika True, endpoint GET memerlukan API key",
    )

    # TODO: Nilai konstanta jenis event untuk E-stop ditekan dan dilepas.
    # Dikonfirmasi oleh pengguna: 'estop_tekan' dan 'estop_lepas'.
    # Dapat diubah via environment variable jika ada penyesuaian di masa depan.
    EVENT_JENIS_ESTOP_TEKAN: str = Field(
        default="estop_tekan",
        description="Nama jenis event saat tombol E-stop ditekan",
    )
    EVENT_JENIS_ESTOP_LEPAS: str = Field(
        default="estop_lepas",
        description="Nama jenis event saat tombol E-stop dilepas / direset",
    )

    # Konfigurasi Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def mesin_api_keys_map(self) -> Dict[str, str]:
        """Mengembalikan mapping dari mesin_id ke API key.
        
        Contoh: {"mesin-01": "kunci1", "mesin-02": "kunci2"}
        """
        mapping: Dict[str, str] = {}
        if not self.MESIN_API_KEYS:
            return mapping

        pairs = self.MESIN_API_KEYS.split(",")
        for pair in pairs:
            pair = pair.strip()
            if not pair:
                continue
            if ":" in pair:
                mesin_id, key = pair.split(":", 1)
                mapping[mesin_id.strip()] = key.strip()
        return mapping


@lru_cache
def get_settings() -> Settings:
    return Settings()
