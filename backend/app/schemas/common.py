"""Shared response envelope and RFC 7807 problem model."""

from __future__ import annotations

from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Meta(BaseModel):
    """What the numbers in ``data`` mean, so the UI never has to guess."""

    generated_at: datetime
    window_from: date | None = Field(default=None, description="First delivery day (UK)")
    window_to: date | None = Field(default=None, description="Exclusive end delivery day (UK)")
    requested_from: date | None = None
    requested_to: date | None = None
    cutoff: str | None = Field(default=None, description="Decision cutoff, UK local HH:MM")
    cutoff_days_before: int | None = Field(default=None, description="Cutoff is on D-n")
    completeness: float | None = Field(default=None, ge=0, le=1)
    clamped: bool = Field(default=False, description="Window was trimmed to available data")
    data_version: int | None = None
    notes: list[str] = Field(default_factory=list)


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: Meta


class Problem(BaseModel):
    """RFC 7807 problem details."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
