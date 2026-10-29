"""Ingest job request/response models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IngestRunCreate(BaseModel):
    dataset: Literal["ALL", "FUELHH", "WINDFOR"] = "ALL"
    delivery_from: date | None = Field(default=None, description="Defaults to the seed window")
    delivery_to: date | None = Field(default=None, description="Exclusive")
    mode: Literal["refresh", "read_through"] = Field(
        default="refresh", description="refresh = always call Elexon; read_through = cache first"
    )

    @model_validator(mode="after")
    def _window(self) -> IngestRunCreate:
        if self.delivery_from and self.delivery_to:
            if self.delivery_from >= self.delivery_to:
                raise ValueError("delivery_from must be before delivery_to")
            if (self.delivery_to - self.delivery_from).days > 400:
                raise ValueError("window may not exceed 400 days")
        return self


class IngestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset: str
    mode: str
    window_from: date
    window_to: date
    status: Literal["running", "succeeded", "partial", "failed"]
    slices_total: int
    slices_done: int
    progress: float = Field(ge=0, le=1)
    rows_fetched: int
    rows_upserted: int
    rows_rejected: int
    quality: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None
    error: str | None

    @model_validator(mode="before")
    @classmethod
    def _progress(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            v = {k: getattr(v, k) for k in cls.model_fields if k != "progress"}
        total = v.get("slices_total") or 0
        v["progress"] = (v.get("slices_done", 0) / total) if total else 0.0
        return v
