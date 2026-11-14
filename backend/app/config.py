"""TerraTrace AI application configuration.

Configuration is environment driven (12-factor). Values can be provided through
a `.env` file (see `.env.example`) or real environment variables.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]  # .../backend
PROJECT_ROOT = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(BASE_DIR / ".env"), str(PROJECT_ROOT / ".env")],
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application ---
    app_name: str = "TerraTrace AI"
    version: str = "0.1.0"
    api_prefix: str = "/api"
    debug: bool = False
    log_level: str = "INFO"

    # --- storage ---
    database_url: str = f"sqlite:///{BASE_DIR / 'terratrace.db'}"
    data_dir: Path = BASE_DIR / "data"
    cache_dir: Path = BASE_DIR / "data" / "cache"
    artifacts_dir: Path = BASE_DIR / "data" / "artifacts"
    max_download_mb: int = 512  # bounded downloads

    # --- processing ---
    job_workers: int = 2
    agent_max_workers: int = 4
    agent_timeout_s: float = 120.0
    agent_retries: int = 1
    max_observations: int = 12
    raster_size: int = 768  # working raster size (pixels) for a region window
    http_timeout_s: float = 30.0
    cache_ttl_s: int = 6 * 3600

    # --- credentials (server side, never exposed to the frontend) ---
    earthdata_username: Optional[str] = None
    earthdata_password: Optional[str] = None
    earthdata_token: Optional[str] = None
    copernicus_client_id: Optional[str] = None
    copernicus_client_secret: Optional[str] = None
    nasa_earthdata_s3_credentials_url: str = "https://cumulus.asf.earthdatacloud.nasa.gov/s3credentials"

    # --- Supabase (database + storage) ---------------------------------------
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None
    supabase_storage_bucket: str = "terratrace-artifacts"
    # When true, use Supabase Storage for artifacts instead of local filesystem
    use_supabase_storage: bool = False
    user_agent: str = "TerraTraceAI/0.1 (NASA Space Apps Challenge; contact: local)"
    allowed_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ]
    )

    # --- sources (overridable switches) ---
    enable_cmr: bool = True
    enable_planetary_computer: bool = True
    enable_earth_search: bool = True
    enable_copernicus: bool = True

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.cache_dir, self.artifacts_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def earthdata_configured(self) -> bool:
        return bool(
            (self.earthdata_username and self.earthdata_password) or self.earthdata_token
        )


settings = Settings()
settings.ensure_dirs()
