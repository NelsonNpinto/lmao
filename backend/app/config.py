"""Application settings, validated from the environment at startup.

Every tunable that the brief leaves open lives here so it is documented in one
place (see DECISIONS.md) and can be overridden without code changes.
"""

from __future__ import annotations

from datetime import date, time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", ".env"), extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    git_sha: str = "local"

    # Storage
    data_dir: Path = REPO_ROOT / "data"
    database_url: str = ""  # empty -> SQLite file under data_dir

    # Elexon Insights API
    elexon_base_url: str = "https://data.elexon.co.uk/bmrs/api/v1"
    elexon_timeout_s: float = 30.0
    elexon_max_retries: int = 5
    elexon_concurrency: int = 3
    elexon_chunk_days: int = Field(default=7, ge=1, le=31)

    # Seed window (delivery days, half-open). Covers both the "decisions made in
    # January" window and calendar-January delivery, so either view works.
    seed_from: date = date(2026, 1, 1)
    seed_to: date = date(2026, 2, 2)
    seed_on_startup: bool = True

    # Study defaults (delivery days, half-open [from, to) in UK local dates)
    study_from: date = date(2026, 1, 2)
    study_to: date = date(2026, 2, 2)
    # Forecasts are pulled from this many days before the first delivery day so
    # every delivery half-hour has a vintage available at the cutoff.
    forecast_lookback_days: int = Field(default=4, ge=3)

    # Decision defaults
    cutoff_local: time = time(9, 0)  # UK local time on D-1
    cutoff_days_before: int = Field(default=1, ge=1, le=2)
    margin_quantile: float = Field(default=0.90, ge=0.5, le=0.99)
    installed_capacity_mw: float = 30_000.0
    lead_time_buckets_h: list[float] = [0, 6, 12, 24, 36]
    hit_band_mw: float = 500.0
    hit_band_pct: float = 10.0

    # API
    allowed_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    admin_token: str = "dev-admin-token"

    @field_validator("lead_time_buckets_h")
    @classmethod
    def _buckets_sorted(cls, v: list[float]) -> list[float]:
        if v != sorted(v) or len(set(v)) != len(v):
            raise ValueError("lead_time_buckets_h must be strictly increasing")
        return v

    @model_validator(mode="after")
    def _window_and_db(self) -> Settings:
        if self.study_from >= self.study_to:
            raise ValueError("study_from must be before study_to (half-open window)")
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{self.data_dir / 'windsight.db'}"
        if self.env == "prod" and self.admin_token == "dev-admin-token":
            raise ValueError("ADMIN_TOKEN must be set in prod")
        return self

    @property
    def raw_cache_dir(self) -> Path:
        return self.data_dir / "raw"


@lru_cache
def get_settings() -> Settings:
    return Settings()
