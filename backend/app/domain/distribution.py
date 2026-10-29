"""Error distribution, band calibration and time resampling."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from app.domain.margin import MIN_HISTORY_DAYS, known_days_at_cutoff
from app.domain.metrics import (
    MIN_GROUP_N,
    QUANTILES,
    FloatArray,
    complete_rows,
    lead_labels,
    lead_time_bucket,
)

Resolution = Literal["30m", "1h", "1d"]


@dataclass(frozen=True)
class Histogram:
    edges: list[float]
    counts: list[int]
    quantiles: dict[str, float]
    mean: float | None
    n: int
    unit: Literal["MW", "%"]


def error_histogram(aligned: pd.DataFrame, bins: int = 30, normalise: bool = False) -> Histogram:
    """Histogram of signed error; ``normalise`` expresses it as % of the window's mean actual."""
    c = complete_rows(aligned)
    e: FloatArray = c["error_mw"].to_numpy(dtype=float)
    unit: Literal["MW", "%"] = "MW"
    if normalise and len(c) and c["actual_mw"].mean() > 0:
        e = 100 * e / float(c["actual_mw"].mean())
        unit = "%"
    if not len(e):
        return Histogram([], [], {}, None, 0, unit)
    counts, edges = np.histogram(e, bins=bins)
    return Histogram(
        edges=[float(x) for x in edges],
        counts=[int(x) for x in counts],
        quantiles={f"p{round(q * 100)}": float(np.quantile(e, q)) for q in QUANTILES},
        mean=float(e.mean()),
        n=len(e),
        unit=unit,
    )


def forecast_band(
    aligned: pd.DataFrame, lo: float = 0.1, hi: float = 0.9
) -> tuple[float, float] | None:
    """Error quantiles (P10, P90 by default) of the window, used for the shaded band.

    actual = forecast - error, so the band for actual is [forecast - P90, forecast - P10].
    """
    c = complete_rows(aligned)
    if c.empty:
        return None
    e = c["error_mw"].to_numpy(dtype=float)
    return float(np.quantile(e, lo)), float(np.quantile(e, hi))


@dataclass(frozen=True)
class CalibrationBucket:
    bucket: str
    n: int
    inside_in_sample_pct: float | None
    inside_walk_forward_pct: float | None
    n_walk_forward: int
    low_n: bool


def calibration(
    aligned: pd.DataFrame,
    *,
    lo: float = 0.1,
    hi: float = 0.9,
    lead_edges: Sequence[float] = (0, 6, 12, 24, 36),
) -> tuple[float, list[CalibrationBucket]]:
    """Share of actuals inside the [P_lo, P_hi] error band, per lead-time bucket.

    In-sample uses the whole window's quantiles. Walk-forward uses, for each day,
    quantiles from days fully known at its cutoff (same rule as the margin backtest).
    Returns the nominal coverage and one row per bucket.
    """
    c = complete_rows(aligned).copy()
    nominal = 100 * (hi - lo)
    if c.empty:
        return nominal, []
    e = c["error_mw"].to_numpy(dtype=float)
    q_lo, q_hi = np.quantile(e, [lo, hi])
    c["inside_is"] = (e >= q_lo) & (e <= q_hi)

    known = known_days_at_cutoff(aligned)
    c["inside_wf"] = pd.NA
    for day, idx in c.groupby("delivery_date").groups.items():
        hist = known.get(day, [])  # type: ignore[call-overload]
        if len(hist) < MIN_HISTORY_DAYS:
            continue
        he = c.loc[c["delivery_date"].isin(hist), "error_mw"].to_numpy(dtype=float)
        d_lo, d_hi = np.quantile(he, [lo, hi])
        de = c.loc[idx, "error_mw"]
        c.loc[idx, "inside_wf"] = (de >= d_lo) & (de <= d_hi)

    c["bucket"] = lead_time_bucket(c["lead_time_h"], lead_edges).fillna("no forecast")
    out: list[CalibrationBucket] = []
    for label in lead_labels(lead_edges):
        g = c[c["bucket"] == label]
        if g.empty:
            continue
        wf = g["inside_wf"].dropna()
        out.append(
            CalibrationBucket(
                bucket=label,
                n=len(g),
                inside_in_sample_pct=float(100 * g["inside_is"].mean()),
                inside_walk_forward_pct=float(100 * wf.astype(bool).mean()) if len(wf) else None,
                n_walk_forward=len(wf),
                low_n=len(g) < MIN_GROUP_N,
            )
        )
    return nominal, out


RESAMPLE_RULE = {"1h": "h", "1d": "D"}
MAX_POINTS = 5_000


def choose_resolution(n_half_hours: int, requested: Resolution) -> Resolution:
    """Coarsen until the series fits in MAX_POINTS (half-hour -> hourly -> daily)."""
    order: list[Resolution] = ["30m", "1h", "1d"]
    per = {"30m": 1, "1h": 2, "1d": 48}
    for r in order[order.index(requested) :]:
        if n_half_hours / per[r] <= MAX_POINTS:
            return r
    return "1d"


def resample_series(series: pd.DataFrame, resolution: Resolution) -> pd.DataFrame:
    """Average MW columns into hourly or UK-daily buckets; a bucket with any missing
    half-hour reports null rather than a mean of what happens to exist."""
    if resolution == "30m":
        return series
    df = series.copy()
    if resolution == "1d":
        df["bucket"] = pd.to_datetime(
            df["start_time"].dt.tz_convert("Europe/London").dt.normalize()
        ).dt.tz_convert("UTC")
    else:
        df["bucket"] = df["start_time"].dt.floor(RESAMPLE_RULE[resolution])
    mw = ["actual_mw", "forecast_mw", "error_mw", "band_low_mw", "band_high_mw"]
    g = df.groupby("bucket", sort=True)
    out = g[mw].mean()
    complete = g[mw].count().eq(g.size(), axis=0)
    out = out.where(complete)
    out["publish_time"] = g["publish_time"].max()
    out["lead_time_h"] = g["lead_time_h"].mean()
    out["stale"] = g["stale"].any()
    return out.reset_index().rename(columns={"bucket": "start_time"})
