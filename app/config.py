"""Konfigurasi aplikasi menggunakan pydantic-settings."""

from functools import lru_cache
from typing import List, Set
from pydantic import Field
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

    # API Key tunggal untuk semua pengirim
    API_KEY: str = Field(
        default="rahasia-api-key",
        description="Kunci API tunggal untuk autentikasi pengiriman data",
    )

    # Pengaturan endpoint baca
    REQUIRE_KEY_FOR_READ: bool = Field(
        default=False,
        description="Jika True, endpoint GET memerlukan API key",
    )

    # Daftar nama pengguna yang sah dipisahkan koma
    PENGGUNA_VALID: str = Field(
        default="gibral,haikal,alvin,naya",
        description="Daftar nama pengguna yang sah dipisahkan tanda koma",
    )

    # Konstanta jenis event untuk E-stop ditekan dan dilepas
    # TODO: Nilai jenis event dikonfirmasi menggunakan 'estop_tekan' dan 'estop_lepas'.
    # Dapat dikonfigurasi melalui environment variable.
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
    def pengguna_valid_list(self) -> List[str]:
        """Mengembalikan daftar nama pengguna sah dalam huruf kecil."""
        if not self.PENGGUNA_VALID:
            return []
        return [p.strip().lower() for p in self.PENGGUNA_VALID.split(",") if p.strip()]

    @property
    def pengguna_valid_set(self) -> Set[str]:
        """Mengembalikan set nama pengguna sah dalam huruf kecil."""
        return set(self.pengguna_valid_list)


@lru_cache
def get_settings() -> Settings:
    return Settings()
