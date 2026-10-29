"""Alembic environment.

Two entry points:
- CLI (`alembic upgrade head`): builds an async engine from Settings.
- In-process (app startup, tests): app.db.migrate passes a live sync connection
  via ``config.attributes["connection"]``.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from app.config import get_settings
from app.db.models import Base
from app.db.session import make_engine

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = make_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=get_settings().database_url, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    existing = context.config.attributes.get("connection")
    if existing is not None:
        _run(existing)
    else:
        asyncio.run(_run_async())
