"""Accuracy analytics: series, metrics, distributions, cutoff sweep, findings."""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query

from app.api.v1.convert import group_out, metrics_out, nn, records
from app.api.v1.params import CUTOFF_PATTERN, ScopeDep
from app.domain.distribution import (
    calibration,
    choose_resolution,
    error_histogram,
    forecast_band,
    resample_series,
)
from app.domain.findings import SweepPoint, build_findings
from app.domain.metrics import compute_metrics
from app.domain.vintage import CutoffRule
from app.schemas.analytics import (
    Band,
    CalibrationBucketOut,
    CalibrationOut,
    FindingOut,
    GroupOut,
    HistogramOut,
    MetricsOut,
    SeriesOut,
    SeriesPoint,
    SweepRow,
)
from app.schemas.common import Envelope
from app.services.analysis import parse_cutoff

router = APIRouter(tags=["analytics"])

SERIES_COLS = [
    "start_time",
    "actual_mw",
    "forecast_mw",
    "error_mw",
    "band_low_mw",
    "band_high_mw",
    "publish_time",
    "lead_time_h",
    "stale",
]
STANDARD_CUTOFFS = ("07:00", "09:00", "11:00")


@router.get("/series", response_model=Envelope[SeriesOut])
async def series(
    sc: ScopeDep,
    resolution: Annotated[Literal["30m", "1h", "1d"], Query()] = "30m",
) -> Envelope[SeriesOut]:
    """Actual, as-of forecast, error and the historical P10-P90 band per period."""
    al = await sc.analysis.aligned(sc.window, sc.rule)
    res = choose_resolution(len(al), resolution)

    def build() -> SeriesOut:
        band = forecast_band(al)
        df = al.copy()
        df["band_low_mw"] = df["forecast_mw"] - band[1] if band else float("nan")
        df["band_high_mw"] = df["forecast_mw"] - band[0] if band else float("nan")
        out = resample_series(df[SERIES_COLS], res)
        return SeriesOut(
            resolution=res,
            # No data at all: empty arrays, not a grid of nulls (meta.completeness = 0).
            points=[SeriesPoint(**r) for r in records(out, SERIES_COLS)]
            if sc.window.has_data
            else [],
            band=Band(
                low_quantile=0.1, high_quantile=0.9, error_low_mw=band[0], error_high_mw=band[1]
            )
            if band
            else None,
            vintages_used=sorted({nn(t) for t in al["publish_time"].dropna().unique()}),
            gaps=int((~(al["has_actual"] & al["has_forecast"])).sum()),
            stale_periods=int(al["stale"].sum()),
        )

    data = await sc.analysis.compute(("series", sc.window, sc.rule, res), build)
    m = await sc.analysis.summary(sc.window, sc.rule)
    notes = [] if res == resolution else [f"Resolution raised to {res} to stay under 5,000 points."]
    return Envelope(data=data, meta=sc.meta(m.completeness, notes))


@router.get("/metrics/summary", response_model=Envelope[MetricsOut])
async def metrics_summary(sc: ScopeDep) -> Envelope[MetricsOut]:
    """Every headline metric with 95 % day-block bootstrap intervals."""
    m = await sc.analysis.summary(sc.window, sc.rule)
    return Envelope(data=metrics_out(m), meta=sc.meta(m.completeness))


@router.get("/metrics/by/{dimension}", response_model=Envelope[list[GroupOut]])
async def metrics_by_dimension(
    sc: ScopeDep,
    dimension: Annotated[Literal["day", "hour", "weekday", "lead_time", "regime"], Path()],
) -> Envelope[list[GroupOut]]:
    groups = await sc.analysis.by(sc.window, sc.rule, dimension)
    m = await sc.analysis.summary(sc.window, sc.rule)
    return Envelope(data=[group_out(g) for g in groups], meta=sc.meta(m.completeness))


@router.get("/metrics/error-distribution", response_model=Envelope[HistogramOut])
async def error_distribution(
    sc: ScopeDep,
    bins: Annotated[int, Query(ge=5, le=200)] = 30,
    normalise: Annotated[bool, Query(description="Express error as % of mean actual")] = False,
) -> Envelope[HistogramOut]:
    al = await sc.analysis.aligned(sc.window, sc.rule)
    h = await sc.analysis.compute(
        ("hist", sc.window, sc.rule, bins, normalise), lambda: error_histogram(al, bins, normalise)
    )
    m = await sc.analysis.summary(sc.window, sc.rule)
    return Envelope(data=HistogramOut(**h.__dict__), meta=sc.meta(m.completeness))


@router.get("/metrics/calibration", response_model=Envelope[CalibrationOut])
async def metrics_calibration(sc: ScopeDep) -> Envelope[CalibrationOut]:
    """Does the P10-P90 band contain ~80 % of actuals? Per lead-time bucket."""
    al = await sc.analysis.aligned(sc.window, sc.rule)
    edges = sc.analysis.settings.lead_time_buckets_h
    nominal, buckets = await sc.analysis.compute(
        ("calibration", sc.window, sc.rule), lambda: calibration(al, lead_edges=edges)
    )
    m = await sc.analysis.summary(sc.window, sc.rule)
    return Envelope(
        data=CalibrationOut(
            nominal_pct=nominal,
            buckets=[CalibrationBucketOut(**b.__dict__) for b in buckets],
        ),
        meta=sc.meta(m.completeness),
    )


async def _sweep_row(sc: ScopeDep, cutoff: str) -> SweepRow:
    rule = CutoffRule(parse_cutoff(cutoff), sc.rule.days_before)
    al = await sc.analysis.aligned(sc.window, rule)
    m = await sc.analysis.compute(("metrics", sc.window, rule), lambda: compute_metrics(al))
    rec = await sc.analysis.margin(sc.window, rule, sc.analysis.settings.margin_quantile)
    flat, cond = rec.by("walk_forward", "flat"), rec.by("walk_forward", "conditional")
    used = al["publish_time"].dropna().dt.strftime("%H:%M")
    return SweepRow(
        cutoff=cutoff,
        days_before=rule.days_before,
        vintages_used=sorted(used.unique()),
        n=m.n,
        completeness=m.completeness,
        mae_mw=m.mae_mw,
        bias_mw=m.bias_mw,
        p90_error_mw=m.error_quantiles_mw.get("p90"),
        skill_vs_persistence=m.skill_vs_persistence,
        mean_vintage_age_h=nn(al["vintage_age_h"].mean()),
        walk_forward_coverage_pct=flat.coverage_pct,
        walk_forward_over_procured_mwh=flat.over_procured_mwh if flat.n else None,
        conditional_over_procured_mwh=cond.over_procured_mwh if cond.n else None,
    )


@router.get("/metrics/cutoff-sweep", response_model=Envelope[list[SweepRow]])
async def cutoff_sweep(
    sc: ScopeDep,
    cutoffs: Annotated[str, Query(description="Comma-separated UK HH:MM list")] = ",".join(
        STANDARD_CUTOFFS
    ),
) -> Envelope[list[SweepRow]]:
    """'When should we decide?': accuracy and margin per candidate cutoff."""
    items = [c.strip() for c in cutoffs.split(",") if c.strip()]
    bad = [c for c in items if not re.fullmatch(CUTOFF_PATTERN, c)]
    if bad or not items or len(items) > 24:
        raise HTTPException(422, f"cutoffs must be 1-24 HH:MM values; invalid: {bad}")
    rows = list(await asyncio.gather(*(_sweep_row(sc, c) for c in sorted(set(items)))))
    return Envelope(data=rows, meta=sc.meta(rows[0].completeness if rows else None))


@router.get("/findings", response_model=Envelope[list[FindingOut]])
async def findings(sc: ScopeDep) -> Envelope[list[FindingOut]]:
    """3-6 computed, plain-English insights with their numbers and evidence links."""
    m = await sc.analysis.summary(sc.window, sc.rule)
    regimes = await sc.analysis.by(sc.window, sc.rule, "regime")
    rec = await sc.analysis.margin(sc.window, sc.rule, sc.analysis.settings.margin_quantile)
    current = sc.rule.local_time.strftime("%H:%M")
    sweep = []
    for c in sorted({current, *STANDARD_CUTOFFS}):
        row = await _sweep_row(sc, c)
        sweep.append(SweepPoint(c, row.vintages_used[0] if row.vintages_used else None, row.mae_mw))
    items = build_findings(m, regimes, rec, sweep, sc.rule.label)
    return Envelope(data=[FindingOut(**f.__dict__) for f in items], meta=sc.meta(m.completeness))
