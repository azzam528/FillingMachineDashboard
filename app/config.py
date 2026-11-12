"""Konfigurasi aplikasi menggunakan pydantic-settings."""

import json
import logging
from functools import lru_cache
from typing import List, Optional, Set
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("app.config")


class Settings(BaseSettings):
    # Lingkungan aplikasi: development, production, test
    ENVIRONMENT: str = Field(
        default="development",
        description="Lingkungan aplikasi: 'development', 'production', atau 'test'",
    )

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

    # Konfigurasi Routing & Base URL API
    API_V1_STR: str = Field(
        default="/api",
        description="Prefix routing API (default: /api)",
    )
    API_PREFIX: str = Field(
        default="/api",
        description="Alias prefix routing API (default: /api)",
    )
    API_BASE_URL: str = Field(
        default="",
        description="Base URL publik API jika diakses di balik reverse proxy atau domain tertentu",
    )

    # Konfigurasi CORS (Cross-Origin Resource Sharing) untuk Frontend MES
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
        description="Daftar origin CORS frontend yang diizinkan (dipisahkan koma atau JSON array)",
    )
    FRONTEND_URL: Optional[str] = Field(
        default=None,
        description="URL frontend MES spesifik opsional untuk ditambahkan ke whitelist CORS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        """Mengidentifikasi apakah berjalan di lingkungan production."""
        return self.ENVIRONMENT.strip().lower() in ("production", "prod")

    @property
    def is_development(self) -> bool:
        """Mengidentifikasi apakah berjalan di lingkungan development."""
        return self.ENVIRONMENT.strip().lower() in ("development", "dev", "local")

    @property
    def is_test(self) -> bool:
        """Mengidentifikasi apakah berjalan di lingkungan test."""
        return self.ENVIRONMENT.strip().lower() in ("test", "testing")

    @model_validator(mode="after")
    def validate_environment_and_cors(self) -> "Settings":
        """Validasi pemisahan lingkungan, CORS, dan URL konfigurasi."""
        # Migrasi otomatis jika nilai masih menggunakan /api/v1 lama dari .env
        if self.API_V1_STR == "/api/v1":
            self.API_V1_STR = "/api"
        if self.API_PREFIX == "/api/v1":
            self.API_PREFIX = "/api"

        # Sinkronkan API_PREFIX dan API_V1_STR jika salah satunya diatur secara kustom
        if self.API_PREFIX != "/api" and self.API_V1_STR == "/api":
            self.API_V1_STR = self.API_PREFIX
        elif self.API_V1_STR != "/api" and self.API_PREFIX == "/api":
            self.API_PREFIX = self.API_V1_STR

        # Di lingkungan production, terapkan aturan keamanan ketat
        if self.is_production:
            # 1. Tolak wildcard '*' pada CORS_ORIGINS di production
            raw_origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
            if any(o == "*" or "*" in o for o in raw_origins):
                raise ValueError(
                    "Wildcard '*' dilarang untuk CORS_ORIGINS pada environment production. "
                    "Harap tentukan domain frontend MES yang sebenarnya (misal: https://mes.fillingmachine.domainkamu.com)."
                )
            # 2. Pastikan DEBUG dimatikan di production
            if self.DEBUG:
                logger.warning("DEBUG bernilai True pada mode production! Otomatis dinonaktifkan demi keamanan.")
                self.DEBUG = False

        return self

    @property
    def cors_origins_list(self) -> List[str]:
        """Mengembalikan daftar origin CORS unik yang sah tanpa trailing slash."""
        origins: List[str] = []
        raw_list: List[str] = []

        if self.CORS_ORIGINS:
            raw = self.CORS_ORIGINS.strip()
            if raw.startswith("[") and raw.endswith("]"):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        raw_list.extend(str(item) for item in parsed)
                    else:
                        raw_list.append(raw)
                except Exception:
                    raw_list.extend(raw.split(","))
            else:
                raw_list.extend(raw.split(","))

        if self.FRONTEND_URL:
            raw_list.append(self.FRONTEND_URL)

        for item in raw_list:
            cleaned = item.strip().rstrip("/")
            if not cleaned:
                continue
            # Proteksi ekstra: jangan masukkan wildcard '*' jika production
            if self.is_production and (cleaned == "*" or "*" in cleaned):
                continue
            if cleaned not in origins:
                origins.append(cleaned)

        return origins

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
