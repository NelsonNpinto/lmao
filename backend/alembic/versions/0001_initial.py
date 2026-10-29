"""initial schema: wind_actual, wind_forecast, ingest_run

Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _provenance() -> list[sa.Column[object]]:
    return [
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", UTCDateTime(), nullable=False),
        sa.Column("ingest_run_id", sa.String(36), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "wind_actual",
        sa.Column("start_time", UTCDateTime(), primary_key=True),
        sa.Column("fuel_type", sa.String(16), primary_key=True),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column("settlement_period", sa.Integer(), nullable=False),
        sa.Column("generation_mw", sa.Float(), nullable=False),
        sa.Column("publish_time", UTCDateTime(), nullable=False),
        sa.Column("revision_count", sa.Integer(), nullable=False),
        *_provenance(),
    )
    op.create_table(
        "wind_forecast",
        sa.Column("start_time", UTCDateTime(), primary_key=True),
        sa.Column("publish_time", UTCDateTime(), primary_key=True),
        sa.Column("generation_mw", sa.Float(), nullable=False),
        sa.Column("lead_time_h", sa.Float(), nullable=False),
        *_provenance(),
    )
    op.create_index("ix_wind_forecast_publish_time", "wind_forecast", ["publish_time"])
    op.create_table(
        "ingest_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("window_from", sa.Date(), nullable=False),
        sa.Column("window_to", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("slices_total", sa.Integer(), nullable=False),
        sa.Column("slices_done", sa.Integer(), nullable=False),
        sa.Column("rows_fetched", sa.Integer(), nullable=False),
        sa.Column("rows_upserted", sa.Integer(), nullable=False),
        sa.Column("rows_rejected", sa.Integer(), nullable=False),
        sa.Column("quality", sa.JSON(), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=False),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_ingest_run_started_at", "ingest_run", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_ingest_run_started_at", table_name="ingest_run")
    op.drop_table("ingest_run")
    op.drop_index("ix_wind_forecast_publish_time", table_name="wind_forecast")
    op.drop_table("wind_forecast")
    op.drop_table("wind_actual")
