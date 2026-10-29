"""Forecast accuracy metrics over an aligned frame (see docs/METHODOLOGY.md).

Every function is pure and NaN-safe: an undefined value (empty input, zero
denominator) is returned as ``None``, never NaN or infinity.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
import pandas as pd

QUANTILES: tuple[float, ...] = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
MIN_GROUP_N = 30  # buckets smaller than this are flagged low-confidence (Break #14)
MIN_DAY_COMPLETENESS = 0.9  # days below this are excluded from daily rankings
MIN_BOOTSTRAP_DAYS = 5

Dimension = Literal["day", "hour", "weekday", "lead_time", "regime"]
FloatArray = npt.NDArray[np.float64]


def _f(x: float | np.floating[Any] | None) -> float | None:
    if x is None:
        return None
    v = float(x)
    return v if np.isfinite(v) else None


def _div(num: float, den: float) -> float | None:
    return _f(num / den) if den else None


@dataclass(frozen=True)
class MetricsResult:
    n: int  # half-hours with both forecast and actual
    n_expected: int  # half-hours in the window
    n_days: int
    n_independent: int  # distinct forecast values (hourly WINDFOR -> n/2)
    completeness: float | None
    mean_actual_mw: float | None
    mean_forecast_mw: float | None
    mae_mw: float | None
    rmse_mw: float | None
    bias_mw: float | None
    nmae_mean_pct: float | None
    nmae_capacity_pct: float | None
    wmape_pct: float | None
    correlation: float | None
    r2: float | None
    error_quantiles_mw: dict[str, float | None]
    hit_rate_mw_pct: float | None
    hit_rate_pct_pct: float | None
    persistence_mae_mw: float | None
    skill_vs_persistence: float | None
    intervals: dict[str, tuple[float, float]] | None = field(default=None)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def complete_rows(aligned: pd.DataFrame) -> pd.DataFrame:
    return aligned[aligned["has_forecast"] & aligned["has_actual"]]


def compute_metrics(
    aligned: pd.DataFrame,
    *,
    capacity_mw: float | None = None,
    band_mw: float = 500.0,
    band_pct: float = 10.0,
    quantiles: Sequence[float] = QUANTILES,
) -> MetricsResult:
    c = complete_rows(aligned)
    e: FloatArray = c["error_mw"].to_numpy(dtype=float)
    a: FloatArray = c["actual_mw"].to_numpy(dtype=float)
    f: FloatArray = c["forecast_mw"].to_numpy(dtype=float)
    n = len(c)
    abs_e = np.abs(e)

    mae = _f(abs_e.mean()) if n else None
    mean_a = _f(a.mean()) if n else None
    sst = float(((a - a.mean()) ** 2).sum()) if n else 0.0
    corr = None
    if n >= 2 and a.std() > 0 and f.std() > 0:
        corr = _f(np.corrcoef(f, a)[0, 1])

    # Skill is compared on the same half-hours (persistence can be missing).
    p = c[c["persistence_mw"].notna()]
    p_mae = _f(p["persistence_error_mw"].abs().mean()) if len(p) else None
    f_mae_common = _f(p["error_mw"].abs().mean()) if len(p) else None
    skill = _f(1 - f_mae_common / p_mae) if p_mae and f_mae_common is not None else None

    return MetricsResult(
        n=n,
        n_expected=len(aligned),
        n_days=int(aligned["delivery_date"].nunique()),
        n_independent=int(c["forecast_hour"].nunique()) if n else 0,
        completeness=_div(n, len(aligned)),
        mean_actual_mw=mean_a,
        mean_forecast_mw=_f(f.mean()) if n else None,
        mae_mw=mae,
        rmse_mw=_f(np.sqrt((e**2).mean())) if n else None,
        bias_mw=_f(e.mean()) if n else None,
        nmae_mean_pct=_div(100 * mae, mean_a) if mae is not None and mean_a else None,
        nmae_capacity_pct=_div(100 * mae, capacity_mw) if mae is not None and capacity_mw else None,
        wmape_pct=_div(100 * float(abs_e.sum()), float(a.sum())) if n else None,
        correlation=corr,
        r2=_f(1 - float((e**2).sum()) / sst) if sst > 0 else None,
        error_quantiles_mw={
            f"p{round(q * 100)}": (_f(np.quantile(e, q)) if n else None) for q in quantiles
        },
        hit_rate_mw_pct=_f(100 * (abs_e <= band_mw).mean()) if n else None,
        hit_rate_pct_pct=_f(100 * (abs_e <= band_pct / 100 * a).mean()) if n else None,
        persistence_mae_mw=p_mae,
        skill_vs_persistence=skill,
    )


# -- confidence intervals ----------------------------------------------------

Stat = Callable[[FloatArray], float]

# Column order of the per-day arrays fed to the bootstrap statistics.
_E, _PE = 0, 1


def _skill(x: FloatArray) -> float:
    m = ~np.isnan(x[:, _PE])
    pm = np.abs(x[m, _PE]).mean() if m.any() else np.nan
    return float(1 - np.abs(x[m, _E]).mean() / pm) if pm else float("nan")


BOOTSTRAP_STATS: dict[str, Stat] = {
    "mae_mw": lambda x: float(np.abs(x[:, _E]).mean()),
    "rmse_mw": lambda x: float(np.sqrt((x[:, _E] ** 2).mean())),
    "bias_mw": lambda x: float(x[:, _E].mean()),
    "p90_mw": lambda x: float(np.quantile(x[:, _E], 0.9)),
    "skill_vs_persistence": _skill,
}


def day_block_bootstrap(
    aligned: pd.DataFrame,
    stats: dict[str, Stat] | None = None,
    *,
    n_boot: int = 1000,
    alpha: float = 0.05,
    seed: int = 0,
) -> dict[str, tuple[float, float]] | None:
    """Percentile intervals from resampling whole delivery days with replacement.

    Half-hours within a day are strongly autocorrelated, so resampling them
    individually would make intervals far too narrow. Returns None with fewer
    than ``MIN_BOOTSTRAP_DAYS`` days.
    """
    stats = stats or BOOTSTRAP_STATS
    c = complete_rows(aligned)
    blocks = [
        g[["error_mw", "persistence_error_mw"]].to_numpy(dtype=float)
        for _, g in c.groupby("delivery_date", sort=True)
    ]
    if len(blocks) < MIN_BOOTSTRAP_DAYS:
        return None
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(blocks), size=(n_boot, len(blocks)))
    samples: dict[str, list[float]] = {k: [] for k in stats}
    for idx in draws:
        x = np.concatenate([blocks[i] for i in idx])
        for k, fn in stats.items():
            samples[k].append(fn(x))
    out: dict[str, tuple[float, float]] = {}
    for k, vals in samples.items():
        arr = np.asarray(vals)
        arr = arr[np.isfinite(arr)]
        if len(arr):
            lo, hi = np.quantile(arr, [alpha / 2, 1 - alpha / 2])
            out[k] = (float(lo), float(hi))
    return out


def summary(aligned: pd.DataFrame, **kw: Any) -> MetricsResult:
    """Headline metrics plus day-block bootstrap intervals."""
    m = compute_metrics(aligned, **kw)
    return MetricsResult(**{**m.__dict__, "intervals": day_block_bootstrap(aligned)})


# -- breakdowns --------------------------------------------------------------


def lead_labels(edges: Sequence[float]) -> list[str]:
    """Edges [0, 6, 12] -> ['0-6 h', '6-12 h', '12+ h'] with an en dash (half-open)."""
    bounds = [*edges, np.inf]
    return [
        f"{lo:g}\u2013{hi:g} h" if np.isfinite(hi) else f"{lo:g}+ h" for lo, hi in pairwise(bounds)
    ]


def lead_time_bucket(lead_h: pd.Series, edges: Sequence[float]) -> pd.Series:
    bounds = [*edges, np.inf]
    return pd.cut(lead_h, bins=bounds, labels=lead_labels(edges), right=False).astype("string")


def wind_regime(aligned: pd.DataFrame) -> pd.Series:
    """Tag each row calm / moderate / windy by its day's mean actual (terciles across days)."""
    daily = aligned.groupby("delivery_date")["actual_mw"].mean().dropna()
    if len(daily) < 3:
        return pd.Series("n/a", index=aligned.index, dtype="string")
    tags = pd.qcut(daily.rank(method="first"), 3, labels=["calm", "moderate", "windy"])
    return aligned["delivery_date"].map(tags.astype(str)).fillna("n/a").astype("string")


@dataclass(frozen=True)
class GroupMetrics:
    key: str
    metrics: MetricsResult
    low_n: bool  # n < MIN_GROUP_N: grey out, do not over-interpret
    excluded_from_ranking: bool  # day completeness < MIN_DAY_COMPLETENESS


WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def metrics_by(
    aligned: pd.DataFrame,
    dimension: Dimension,
    *,
    lead_edges: Sequence[float] = (0, 6, 12, 24, 36),
    **kw: Any,
) -> list[GroupMetrics]:
    if dimension == "day":
        keys = aligned["delivery_date"].map(lambda d: d.isoformat())
    elif dimension == "hour":
        keys = aligned["hour_of_day"].map(lambda h: f"{h:02d}:00")
    elif dimension == "weekday":
        keys = aligned["weekday"].map(lambda w: WEEKDAYS[w])
    elif dimension == "lead_time":
        keys = lead_time_bucket(aligned["lead_time_h"], lead_edges).fillna("no forecast")
    elif dimension == "regime":
        keys = wind_regime(aligned)
    else:  # pragma: no cover - guarded by the Literal type and API validation
        raise ValueError(f"unknown dimension {dimension}")

    present = set(keys)
    canonical: dict[str, list[str]] = {
        "weekday": list(WEEKDAYS),
        "lead_time": [*lead_labels(lead_edges), "no forecast"],
        "regime": ["calm", "moderate", "windy", "n/a"],
    }
    order = (
        [k for k in canonical[dimension] if k in present]
        if dimension in canonical
        else sorted(present)
    )
    out: list[GroupMetrics] = []
    for k in order:
        m = compute_metrics(aligned[keys == k], **kw)
        out.append(
            GroupMetrics(
                key=str(k),
                metrics=m,
                low_n=m.n < MIN_GROUP_N,
                excluded_from_ranking=dimension == "day"
                and (m.completeness or 0) < MIN_DAY_COMPLETENESS,
            )
        )
    return out
