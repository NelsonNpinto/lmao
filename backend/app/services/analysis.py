"""Bridges the database, the pure domain functions and the API.

The whole dataset is small (about 23k rows for the January window), so it is
loaded once per data version and every analysis is memoised by
``(data_version, window, cutoff, ...)``. An ingest that changes rows bumps the
version, which invalidates everything (Break #18). CPU-bound work runs in a
worker thread so the event loop stays responsive.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from typing import Any, TypeVar

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import repositories as repo
from app.domain.align import build_aligned
from app.domain.margin import MarginRecommendation, Policy, recommend, walk_forward
from app.domain.metrics import MetricsResult, compute_metrics, metrics_by, summary
from app.domain.vintage import CutoffRule, local_dates
from app.logging import get_logger

log = get_logger(__name__)
T = TypeVar("T")

FAR_PAST = datetime(2000, 1, 1, tzinfo=UTC)
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Frames:
    version: int
    actuals: pd.DataFrame
    forecasts: pd.DataFrame
    first_day: date | None  # first UK delivery day with actuals
    last_day: date | None  # last UK delivery day with actuals (inclusive)


@dataclass(frozen=True)
class Window:
    day_from: date
    day_to: date  # exclusive
    requested_from: date
    requested_to: date
    clamped: bool
    has_data: bool


class AnalysisService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        version: Callable[[], int],
        max_entries: int = 256,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._version = version
        self._frames: Frames | None = None
        self._load_lock = asyncio.Lock()
        self._cache: OrderedDict[Hashable, Any] = OrderedDict()
        self._max = max_entries

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def version(self) -> int:
        return self._version()

    # -- data ----------------------------------------------------------------

    async def frames(self) -> Frames:
        v = self.version
        if self._frames is not None and self._frames.version == v:
            return self._frames
        async with self._load_lock:
            if self._frames is not None and self._frames.version == v:
                return self._frames
            async with self._sessionmaker() as s:
                actuals = await repo.load_actuals_df(s, FAR_PAST, FAR_FUTURE)
                forecasts = await repo.load_forecasts_df(s, FAR_PAST, FAR_FUTURE)
            days = local_dates(actuals["start_time"]) if len(actuals) else pd.Series(dtype=object)
            self._frames = Frames(
                version=v,
                actuals=actuals,
                forecasts=forecasts,
                first_day=min(days) if len(days) else None,
                last_day=max(days) if len(days) else None,
            )
            self._cache.clear()
            log.info(
                "analysis_frames_loaded", version=v, actuals=len(actuals), forecasts=len(forecasts)
            )
            return self._frames

    async def window(self, requested_from: date | None, requested_to: date | None) -> Window:
        """Default to the configured study window; clamp to the days that have data.

        No overlap at all is not an error: the window is kept as requested and
        every result reports completeness 0.
        """
        rf = requested_from or self._settings.study_from
        rt = requested_to or self._settings.study_to
        f = await self.frames()
        if f.first_day is None or f.last_day is None:
            return Window(rf, rt, rf, rt, clamped=False, has_data=False)
        lo = max(rf, f.first_day)
        hi = min(rt, f.last_day + timedelta(days=1))
        if lo >= hi:
            return Window(rf, rt, rf, rt, clamped=False, has_data=False)
        return Window(lo, hi, rf, rt, clamped=(lo, hi) != (rf, rt), has_data=True)

    # -- memoised analyses ---------------------------------------------------

    async def _memo(self, key: tuple[Any, ...], fn: Callable[[], T]) -> T:
        full = (self.version, *key)
        if full in self._cache:
            self._cache.move_to_end(full)
            return self._cache[full]  # type: ignore[no-any-return]
        value = await asyncio.to_thread(fn)
        self._cache[full] = value
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)
        return value

    async def aligned(self, w: Window, rule: CutoffRule) -> pd.DataFrame:
        f = await self.frames()
        return await self._memo(
            ("aligned", w.day_from, w.day_to, rule),
            lambda: build_aligned(f.actuals, f.forecasts, w.day_from, w.day_to, rule),
        )

    async def summary(self, w: Window, rule: CutoffRule) -> MetricsResult:
        al = await self.aligned(w, rule)
        s = self._settings
        return await self._memo(
            ("summary", w.day_from, w.day_to, rule),
            lambda: summary(
                al,
                capacity_mw=s.installed_capacity_mw,
                band_mw=s.hit_band_mw,
                band_pct=s.hit_band_pct,
            ),
        )

    async def by(self, w: Window, rule: CutoffRule, dimension: str) -> list[Any]:
        al = await self.aligned(w, rule)
        s = self._settings
        return await self._memo(
            ("by", w.day_from, w.day_to, rule, dimension),
            lambda: metrics_by(
                al,
                dimension,  # type: ignore[arg-type]
                lead_edges=s.lead_time_buckets_h,
                capacity_mw=s.installed_capacity_mw,
                band_mw=s.hit_band_mw,
                band_pct=s.hit_band_pct,
            ),
        )

    async def margin(self, w: Window, rule: CutoffRule, q: float) -> MarginRecommendation:
        al = await self.aligned(w, rule)
        return await self._memo(("margin", w.day_from, w.day_to, rule, q), lambda: recommend(al, q))

    async def walk_forward_days(
        self, w: Window, rule: CutoffRule, q: float, policy: Policy
    ) -> pd.DataFrame:
        al = await self.aligned(w, rule)
        return await self._memo(
            ("wf_days", w.day_from, w.day_to, rule, q, policy),
            lambda: walk_forward(al, policy, q)[1],
        )

    async def compute(self, key: tuple[Any, ...], fn: Callable[[], T]) -> T:
        """Memoise any other derived result (distribution, calibration, findings...)."""
        return await self._memo(key, fn)

    async def warm(self) -> None:
        """Precompute the default dashboard view (called at startup)."""
        try:
            w = await self.window(None, None)
            if not w.has_data:
                return
            rule = CutoffRule(self._settings.cutoff_local, self._settings.cutoff_days_before)
            await self.summary(w, rule)
            await self.margin(w, rule, self._settings.margin_quantile)
            # The cutoff explorer sweeps every hour; precompute it so the slider is instant.
            for h in range(24):
                r = CutoffRule(time(h, 0), rule.days_before)
                al = await self.aligned(w, r)
                await self.compute(("metrics", w, r), partial(compute_metrics, al))
                await self.margin(w, r, self._settings.margin_quantile)
            log.info("analysis_warmed", window=f"{w.day_from}..{w.day_to}")
        except Exception:  # warming is best-effort; requests will compute on demand
            log.exception("analysis_warm_failed")


def parse_cutoff(value: str) -> time:
    return time.fromisoformat(value)
