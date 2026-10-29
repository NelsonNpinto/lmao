"""Data access: idempotent upserts, ingest-run bookkeeping, coverage queries."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from itertools import islice
from typing import Any

import pandas as pd
from sqlalchemy import Table, func, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestRun, WindActual, WindForecast

BATCH = 500


def _batched(rows: Sequence[dict[str, Any]], n: int) -> Iterator[list[dict[str, Any]]]:
    it = iter(rows)
    while chunk := list(islice(it, n)):
        yield chunk


def _insert(session: AsyncSession, table: Table) -> Any:
    name = session.get_bind().dialect.name
    if name == "postgresql":
        return postgresql.insert(table)
    if name == "sqlite":
        return sqlite.insert(table)
    raise RuntimeError(f"unsupported dialect {name}")


async def upsert_actuals(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> int:
    """Insert new half-hours; update only when Elexon republished with a later publish_time.

    Returns rows inserted or changed, so an identical re-run returns 0.
    """
    t: Table = WindActual.__table__  # type: ignore[assignment]
    changed = 0
    for batch in _batched([{"revision_count": 0, **r} for r in rows], BATCH):
        ins = _insert(session, t).values(batch)
        ex = ins.excluded
        stmt = ins.on_conflict_do_update(
            index_elements=[t.c.start_time, t.c.fuel_type],
            set_={
                "generation_mw": ex.generation_mw,
                "publish_time": ex.publish_time,
                "settlement_date": ex.settlement_date,
                "settlement_period": ex.settlement_period,
                "revision_count": t.c.revision_count + 1,
                "source_url": ex.source_url,
                "fetched_at": ex.fetched_at,
                "ingest_run_id": ex.ingest_run_id,
            },
            where=ex.publish_time > t.c.publish_time,
        ).returning(t.c.start_time)
        changed += len((await session.execute(stmt)).all())
    return changed


async def upsert_forecasts(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> int:
    """Insert new vintages; a re-sent vintage only updates if its value changed."""
    t: Table = WindForecast.__table__  # type: ignore[assignment]
    changed = 0
    for batch in _batched(rows, BATCH):
        ins = _insert(session, t).values(batch)
        ex = ins.excluded
        stmt = ins.on_conflict_do_update(
            index_elements=[t.c.start_time, t.c.publish_time],
            set_={
                "generation_mw": ex.generation_mw,
                "source_url": ex.source_url,
                "fetched_at": ex.fetched_at,
                "ingest_run_id": ex.ingest_run_id,
            },
            where=t.c.generation_mw != ex.generation_mw,
        ).returning(t.c.start_time)
        changed += len((await session.execute(stmt)).all())
    return changed


# -- ingest runs -------------------------------------------------------------


async def update_run(session: AsyncSession, run_id: str, **fields: Any) -> None:
    await session.execute(update(IngestRun).where(IngestRun.id == run_id).values(**fields))


async def get_run(session: AsyncSession, run_id: str) -> IngestRun | None:
    return await session.get(IngestRun, run_id)


async def list_runs(session: AsyncSession, limit: int = 20) -> list[IngestRun]:
    res = await session.execute(
        select(IngestRun).order_by(IngestRun.started_at.desc()).limit(limit)
    )
    return list(res.scalars())


async def fail_interrupted_runs(session: AsyncSession) -> int:
    """Runs left 'running' by a crash or restart can never finish; mark them failed."""
    res = await session.execute(
        update(IngestRun)
        .where(IngestRun.status == "running")
        .values(status="failed", error="interrupted by restart", finished_at=datetime.now(UTC))
        .returning(IngestRun.id)
    )
    return len(res.all())


# -- coverage ----------------------------------------------------------------


async def coverage(session: AsyncSession) -> dict[str, Any]:
    a = (
        await session.execute(
            select(
                func.count(),
                func.min(WindActual.start_time),
                func.max(WindActual.start_time),
                func.sum(WindActual.revision_count),
            )
        )
    ).one()
    f = (
        await session.execute(
            select(
                func.count(),
                func.count(func.distinct(WindForecast.publish_time)),
                func.min(WindForecast.publish_time),
                func.max(WindForecast.publish_time),
            )
        )
    ).one()
    last = (
        await session.execute(select(IngestRun).order_by(IngestRun.started_at.desc()).limit(1))
    ).scalar_one_or_none()
    return {
        "actual_rows": a[0],
        "actual_from": _utc(a[1]),
        "actual_to": _utc(a[2]),
        "actual_revisions": int(a[3] or 0),
        "forecast_rows": f[0],
        "forecast_vintages": f[1],
        "forecast_published_from": _utc(f[2]),
        "forecast_published_to": _utc(f[3]),
        "last_run": last,
    }


def _utc(v: datetime | None) -> datetime | None:
    # Aggregates bypass the column type, so SQLite returns naive values/strings.
    if v is None:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


async def has_completed_run(session: AsyncSession) -> bool:
    """True once any ingest finished with data. An interrupted seed leaves this False,
    so the next startup retries instead of serving a half-loaded database."""
    q = select(IngestRun.id).where(IngestRun.status.in_(("succeeded", "partial"))).limit(1)
    return (await session.execute(q)).first() is not None


# -- analytics frames --------------------------------------------------------


async def load_actuals_df(session: AsyncSession, start: datetime, end: datetime) -> pd.DataFrame:
    """Actual wind half-hours with start_time in [start, end) as a UTC DataFrame."""
    res = await session.execute(
        select(WindActual.start_time, WindActual.generation_mw)
        .where(WindActual.start_time >= start, WindActual.start_time < end)
        .order_by(WindActual.start_time)
    )
    return _frame(res.all(), ["start_time", "generation_mw"], ["start_time"])


async def load_forecasts_df(session: AsyncSession, start: datetime, end: datetime) -> pd.DataFrame:
    """Every vintage for target start_times in [start, end)."""
    res = await session.execute(
        select(WindForecast.start_time, WindForecast.publish_time, WindForecast.generation_mw)
        .where(WindForecast.start_time >= start, WindForecast.start_time < end)
        .order_by(WindForecast.start_time, WindForecast.publish_time)
    )
    return _frame(
        res.all(), ["start_time", "publish_time", "generation_mw"], ["start_time", "publish_time"]
    )


def _frame(rows: Sequence[Any], cols: list[str], time_cols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame([tuple(r) for r in rows], columns=cols)
    for c in time_cols:
        df[c] = pd.to_datetime(df[c], utc=True)
    df["generation_mw"] = df["generation_mw"].astype(float)
    return df
