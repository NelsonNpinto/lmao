"""SQLAlchemy models. One schema for SQLite (dev, tests) and Postgres (prod)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import UTCDateTime


class Base(DeclarativeBase):
    pass


class ProvenanceMixin:
    source_url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ingest_run_id: Mapped[str] = mapped_column(String(36))


class WindActual(ProvenanceMixin, Base):
    """FUELHH outturn: one row per half-hour (natural key start_time + fuel_type)."""

    __tablename__ = "wind_actual"

    start_time: Mapped[datetime] = mapped_column(UTCDateTime, primary_key=True)
    fuel_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    settlement_date: Mapped[date] = mapped_column(Date)
    settlement_period: Mapped[int] = mapped_column(Integer)
    generation_mw: Mapped[float] = mapped_column(Float)
    publish_time: Mapped[datetime] = mapped_column(UTCDateTime)
    # Times this start_time was republished with a later publish_time (Break #2).
    revision_count: Mapped[int] = mapped_column(Integer, default=0)


class WindForecast(ProvenanceMixin, Base):
    """WINDFOR: every vintage, never collapsed by start_time (ADR 0001)."""

    __tablename__ = "wind_forecast"
    __table_args__ = (Index("ix_wind_forecast_publish_time", "publish_time"),)

    start_time: Mapped[datetime] = mapped_column(UTCDateTime, primary_key=True)
    publish_time: Mapped[datetime] = mapped_column(UTCDateTime, primary_key=True)
    generation_mw: Mapped[float] = mapped_column(Float)
    # start_time - publish_time in hours. Stored rather than a generated column
    # because SQLite and Postgres disagree on interval arithmetic.
    lead_time_h: Mapped[float] = mapped_column(Float)


class IngestRun(Base):
    __tablename__ = "ingest_run"
    __table_args__ = (Index("ix_ingest_run_started_at", "started_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(16))  # FUELHH | WINDFOR | ALL
    mode: Mapped[str] = mapped_column(String(16))  # read_through | refresh | offline
    window_from: Mapped[date] = mapped_column(Date)
    window_to: Mapped[date] = mapped_column(Date)  # exclusive
    status: Mapped[str] = mapped_column(String(16))  # running|succeeded|partial|failed
    slices_total: Mapped[int] = mapped_column(Integer, default=0)
    slices_done: Mapped[int] = mapped_column(Integer, default=0)
    rows_fetched: Mapped[int] = mapped_column(Integer, default=0)
    rows_upserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    quality: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
