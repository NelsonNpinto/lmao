"""Ingest job orchestration: plan slices, fetch concurrently, validate, upsert, track progress.

One run at a time per process (single-flight). Each slice is independent: a
failed slice is recorded and the run ends ``partial`` rather than aborting, so
partial data never masquerades as complete (Break #6).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import repositories as repo
from app.db.models import IngestRun
from app.domain.timeutil import local_day_bounds_utc, periods_in_local_day
from app.ingest.chunking import date_slices, datetime_slices
from app.ingest.elexon_client import CacheMode, ElexonClient, ElexonError, FetchResult
from app.ingest.validate import (
    ContractError,
    QualityCounters,
    validate_fuelhh,
    validate_windfor,
)
from app.logging import get_logger

log = get_logger(__name__)

Dataset = Literal["ALL", "FUELHH", "WINDFOR"]
ClientFactory = Callable[[CacheMode], ElexonClient]


@dataclass(frozen=True)
class IngestRequest:
    """Ingest everything needed to analyse delivery days in [delivery_from, delivery_to)."""

    delivery_from: date
    delivery_to: date
    dataset: Dataset = "ALL"
    mode: CacheMode = "read_through"
    forecast_lookback_days: int = 4
    chunk_days: int = 7

    def __post_init__(self) -> None:
        if self.delivery_from >= self.delivery_to:
            raise ValueError("delivery_from must be before delivery_to")


class IngestAlreadyRunningError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"ingest run {run_id} is already running")
        self.run_id = run_id


@dataclass(frozen=True)
class _Slice:
    dataset: Literal["FUELHH", "WINDFOR"]
    start: Any
    end: Any

    @property
    def label(self) -> str:
        return f"{self.dataset} {self.start}..{self.end}"


@dataclass
class _RunState:
    rows_fetched: int = 0
    rows_upserted: int = 0
    rows_rejected: int = 0
    slices_done: int = 0
    cached_slices: int = 0
    quality: dict[str, dict[str, int]] = field(
        default_factory=lambda: {"FUELHH": {}, "WINDFOR": {}}
    )
    periods_by_day: dict[str, int] = field(default_factory=dict)
    forecast_minutes: set[int] = field(default_factory=set)
    empty_slices: list[str] = field(default_factory=list)
    slice_errors: list[str] = field(default_factory=list)
    contract_error: bool = False


def plan_slices(req: IngestRequest) -> list[_Slice]:
    """Actuals from D-1 of the first day (persistence baseline) to the last delivery day.
    Forecast vintages from ``forecast_lookback_days`` before the first day until the end
    of the last day, so every cutoff and the full vintage fan are covered.
    """
    out: list[_Slice] = []
    if req.dataset in ("ALL", "FUELHH"):
        a_from = req.delivery_from - timedelta(days=1)
        out += [
            _Slice("FUELHH", a, b) for a, b in date_slices(a_from, req.delivery_to, req.chunk_days)
        ]
    if req.dataset in ("ALL", "WINDFOR"):
        p_from, _ = local_day_bounds_utc(
            req.delivery_from - timedelta(days=req.forecast_lookback_days)
        )
        p_to, _ = local_day_bounds_utc(req.delivery_to)
        out += [_Slice("WINDFOR", a, b) for a, b in datetime_slices(p_from, p_to, req.chunk_days)]
    return out


class IngestRunner:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        client_factory: ClientFactory,
        *,
        concurrency: int = 3,
        on_complete: Callable[[IngestRun], None] | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._client_factory = client_factory
        self._concurrency = concurrency
        self._on_complete = on_complete
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[IngestRun] | None = None
        self._current_id: str | None = None

    @property
    def running_id(self) -> str | None:
        return self._current_id if self._task is not None and not self._task.done() else None

    async def start(self, req: IngestRequest) -> str:
        """Create the run row and execute it in the background. Raises if one is running."""
        async with self._lock:
            if (rid := self.running_id) is not None:
                raise IngestAlreadyRunningError(rid)
            slices = plan_slices(req)
            run = IngestRun(
                id=str(uuid.uuid4()),
                dataset=req.dataset,
                mode=req.mode,
                window_from=req.delivery_from,
                window_to=req.delivery_to,
                status="running",
                slices_total=len(slices),
                slices_done=0,
                rows_fetched=0,
                rows_upserted=0,
                rows_rejected=0,
                quality={},
                started_at=datetime.now(UTC),
            )
            async with self._sessionmaker() as s:
                s.add(run)
                await s.commit()
            self._current_id = run.id
            self._task = asyncio.create_task(self._execute(run.id, req, slices))
            return run.id

    async def run(self, req: IngestRequest) -> IngestRun:
        """Start and wait for completion (CLI, tests, startup seed)."""
        await self.start(req)
        assert self._task is not None
        return await self._task

    async def wait(self) -> None:
        if self._task is not None:
            await asyncio.shield(self._task)

    async def shutdown(self) -> None:
        """Cancel an in-flight run; the next startup marks it failed (interrupted)."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    # -- execution ------------------------------------------------------------

    async def _execute(self, run_id: str, req: IngestRequest, slices: list[_Slice]) -> IngestRun:
        log.info("ingest_start", run_id=run_id, slices=len(slices), mode=req.mode)
        state = _RunState()
        write_lock = asyncio.Lock()
        sem = asyncio.Semaphore(self._concurrency)
        client = self._client_factory(req.mode)
        try:
            async with self._sessionmaker() as session:

                async def one(sl: _Slice) -> None:
                    async with sem:
                        try:
                            res = await self._fetch(client, sl)
                            rows, q = (
                                validate_fuelhh(res.rows)
                                if sl.dataset == "FUELHH"
                                else validate_windfor(res.rows)
                            )
                        except ElexonError as exc:
                            state.contract_error |= isinstance(exc, ContractError)
                            state.slice_errors.append(f"{sl.label}: {exc}")
                            log.error(
                                "ingest_slice_failed", run_id=run_id, slice=sl.label, error=str(exc)
                            )
                            async with write_lock:
                                state.slices_done += 1
                                await self._progress(session, run_id, state)
                            return
                    async with write_lock:
                        prov = {
                            "source_url": res.url,
                            "fetched_at": res.fetched_at,
                            "ingest_run_id": run_id,
                        }
                        rows = [{**r, **prov} for r in rows]
                        upsert = (
                            repo.upsert_actuals if sl.dataset == "FUELHH" else repo.upsert_forecasts
                        )
                        n = await upsert(session, rows)
                        self._accumulate(state, sl, res, q, n)
                        state.slices_done += 1
                        await self._progress(session, run_id, state)
                        log.info(
                            "ingest_slice",
                            run_id=run_id,
                            slice=sl.label,
                            fetched=len(res.rows),
                            accepted=q.accepted,
                            upserted=n,
                            rejected=q.rejected,
                            from_cache=res.from_cache,
                        )

                await asyncio.gather(*(one(sl) for sl in slices))
                return await self._finish(session, run_id, req, state)
        except Exception as exc:  # unexpected bug: never leave a run stuck in 'running'
            log.exception("ingest_crashed", run_id=run_id)
            async with self._sessionmaker() as s:
                await repo.update_run(
                    s,
                    run_id,
                    status="failed",
                    error=f"internal error: {exc}"[:500],
                    finished_at=datetime.now(UTC),
                )
                await s.commit()
                run = await repo.get_run(s, run_id)
            assert run is not None
            return run
        finally:
            await client.aclose()

    @staticmethod
    async def _fetch(client: ElexonClient, sl: _Slice) -> FetchResult:
        if sl.dataset == "FUELHH":
            return await client.fetch_fuelhh(sl.start, sl.end)
        return await client.fetch_windfor(sl.start, sl.end)

    @staticmethod
    def _accumulate(
        state: _RunState, sl: _Slice, res: FetchResult, q: QualityCounters, upserted: int
    ) -> None:
        state.rows_fetched += q.rows_in
        state.rows_upserted += upserted
        state.rows_rejected += q.rejected
        state.cached_slices += int(res.from_cache)
        agg = state.quality[sl.dataset]
        for k in (
            "rows_in",
            "accepted",
            "null_generation",
            "negative_generation",
            "non_wind",
            "duplicates",
        ):
            agg[k] = agg.get(k, 0) + int(getattr(q, k))
        if sl.dataset == "FUELHH":
            state.periods_by_day.update(q.periods_by_day)
            d = sl.start
            while d <= sl.end:
                state.periods_by_day.setdefault(d.isoformat(), 0)
                d += timedelta(days=1)
        else:
            state.forecast_minutes.update(q.start_minutes)
            if q.accepted == 0 and sl.end <= datetime.now(UTC):
                state.empty_slices.append(sl.label)

    @staticmethod
    async def _progress(session: AsyncSession, run_id: str, state: _RunState) -> None:
        await repo.update_run(
            session,
            run_id,
            slices_done=state.slices_done,
            rows_fetched=state.rows_fetched,
            rows_upserted=state.rows_upserted,
            rows_rejected=state.rows_rejected,
        )
        await session.commit()

    async def _finish(
        self, session: AsyncSession, run_id: str, req: IngestRequest, state: _RunState
    ) -> IngestRun:
        now = datetime.now(UTC)
        incomplete = {
            day: {"got": got, "expected": periods_in_local_day(date.fromisoformat(day))}
            for day, got in sorted(state.periods_by_day.items())
            # Only judge days that are fully over and published.
            if local_day_bounds_utc(date.fromisoformat(day))[1] + timedelta(hours=1) <= now
            and got < periods_in_local_day(date.fromisoformat(day))
        }
        quality: dict[str, Any] = {
            **state.quality,
            "incomplete_days": incomplete,
            "forecast_start_minutes": sorted(state.forecast_minutes),
            "forecast_resolution": _resolution(state.forecast_minutes),
            "empty_forecast_slices": state.empty_slices,
            "slice_errors": state.slice_errors,
            "cached_slices": state.cached_slices,
        }
        failed = len(state.slice_errors)
        if state.contract_error or (failed and failed == state.slices_done):
            status = "failed"
        elif failed or incomplete or state.empty_slices:
            status = "partial"
        else:
            status = "succeeded"
        await repo.update_run(
            session,
            run_id,
            status=status,
            quality=quality,
            finished_at=now,
            error=state.slice_errors[0][:500] if state.slice_errors else None,
        )
        await session.commit()
        run = await repo.get_run(session, run_id)
        assert run is not None
        await session.refresh(run)
        log.info(
            "ingest_done",
            run_id=run_id,
            status=status,
            upserted=state.rows_upserted,
            rejected=state.rows_rejected,
            incomplete_days=len(incomplete),
        )
        if self._on_complete is not None:
            self._on_complete(run)
        return run


def _resolution(minutes: set[int]) -> str:
    if not minutes:
        return "unknown"
    if minutes == {0}:
        return "hourly"
    if minutes <= {0, 30}:
        return "half-hourly"
    return "irregular"
