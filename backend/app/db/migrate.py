"""Run Alembic migrations in-process on an existing async engine."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(connection: Connection) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.attributes["connection"] = connection
    return cfg


async def upgrade_to_head(engine: AsyncEngine) -> None:
    def _upgrade(conn: Connection) -> None:
        command.upgrade(_alembic_config(conn), "head")

    async with engine.begin() as conn:
        await conn.run_sync(_upgrade)
