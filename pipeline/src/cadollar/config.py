"""Layered settings: environment (CDT_ prefix) over defaults.

storage_mode:
  local — parquet + manifests under data_dir (dev / dry-run; no cloud creds needed)
  r2    — Cloudflare R2 via the S3-compatible API (production)
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CDT_", env_file=".env", extra="ignore")

    storage_mode: str = "local"  # "local" | "r2"
    data_dir: Path = REPO_ROOT / "data"
    sources_dir: Path = REPO_ROOT / "pipeline" / "sources"

    # R2 (S3-compatible). Endpoint is https://<account_id>.r2.cloudflarestorage.com
    r2_bucket: str = ""
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""

    duckdb_memory_limit: str = "2GB"
    duckdb_threads: int = 4

    @property
    def r2_endpoint(self) -> str:
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"


def get_settings() -> Settings:
    return Settings()
