"""Procurement safety margin from the signed forecast error, with honest backtests.

Sign convention: error = forecast - actual. A positive error means less wind
arrived than forecast, so the desk is short and must top up at intraday or
balancing prices. Planning on ``forecast - margin`` MW of wind covers a
half-hour when ``error <= margin``.

Two evaluations:
- in-sample: margin fitted on the whole window and judged on the same window
  (optimistic; shown for reference only);
- walk-forward: each delivery day's margin is fitted only on days whose actuals
  were fully published before that day's cutoff (no look-ahead, Break #13).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal, cast

import numpy as np
import pandas as pd

from app.domain.metrics import FloatArray, complete_rows
from app.domain.timeutil import local_day_bounds_utc

Policy = Literal["none", "flat", "conditional"]
POLICIES: tuple[Policy, ...] = ("none", "flat", "conditional")
PERIOD_H = 0.5  # MW over a half-hour -> MWh
LEVEL_BINS = 3  # conditional policy: terciles of forecast level
MIN_BIN_N = 30
MIN_HISTORY_DAYS = 7

MarginFn = Callable[[pd.DataFrame], FloatArray]


def fit_policy(train: pd.DataFrame, policy: Policy, q: float) -> MarginFn:
    """Return a function giving the margin (MW) for each row of a test frame."""
    if policy == "none" or train.empty:
        return lambda test: np.zeros(len(test))
    flat = float(np.quantile(train["error_mw"].to_numpy(dtype=float), q))
    if policy == "flat":
        return lambda test: np.full(len(test), flat)

    # Conditional: empirical quantile of the error within forecast-level bins.
    # Edges come from training data only; sparse bins fall back to the flat margin.
    levels = train["forecast_mw"].to_numpy(dtype=float)
    inner = np.quantile(levels, np.linspace(0, 1, LEVEL_BINS + 1)[1:-1])
    train_bin = np.searchsorted(inner, levels, side="right")
    errors = train["error_mw"].to_numpy(dtype=float)
    per_bin = np.array(
        [
            float(np.quantile(errors[train_bin == b], q))
            if (train_bin == b).sum() >= MIN_BIN_N
            else flat
            for b in range(LEVEL_BINS)
        ]
    )

    def conditional(test: pd.DataFrame) -> FloatArray:
        b = np.searchsorted(inner, test["forecast_mw"].to_numpy(dtype=float), side="right")
        return per_bin[b]

    return conditional


@dataclass(frozen=True)
class Backtest:
    policy: Policy
    evaluation: Literal["in_sample", "walk_forward"]
    quantile: float
    n: int
    n_days: int
    days_skipped: int  # walk-forward days without enough history
    coverage_pct: float | None  # share of half-hours with error <= margin
    mean_margin_mw: float | None
    over_procured_mwh: float  # bought but not needed: sum max(0, margin - error) * 0.5
    shortfall_mwh: float  # still short after the margin: sum max(0, error - margin) * 0.5

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _score(
    test: pd.DataFrame,
    margins: FloatArray,
    policy: Policy,
    evaluation: Literal["in_sample", "walk_forward"],
    q: float,
    days_skipped: int = 0,
) -> Backtest:
    e = test["error_mw"].to_numpy(dtype=float)
    n = len(e)
    return Backtest(
        policy=policy,
        evaluation=evaluation,
        quantile=q,
        n=n,
        n_days=int(test["delivery_date"].nunique()),
        days_skipped=days_skipped,
        coverage_pct=float(100 * (e <= margins).mean()) if n else None,
        mean_margin_mw=float(margins.mean()) if n else None,
        over_procured_mwh=float(np.clip(margins - e, 0, None).sum() * PERIOD_H),
        shortfall_mwh=float(np.clip(e - margins, 0, None).sum() * PERIOD_H),
    )


def in_sample(aligned: pd.DataFrame, policy: Policy, q: float) -> Backtest:
    c = complete_rows(aligned)
    return _score(c, fit_policy(c, policy, q)(c), policy, "in_sample", q)


def known_days_at_cutoff(aligned: pd.DataFrame) -> dict[date, list[date]]:
    """For each delivery day, the earlier days whose full actuals existed at its cutoff.

    The last half-hour of day X is published at the end of X, so X is usable
    for day D only if end(X) <= cutoff(D). At a 09:00 D-1 cutoff that is D-2
    and earlier: yesterday is still in progress.
    """
    cut = aligned.groupby("delivery_date")["cutoff"].min()
    days = cast(list[date], list(cut.index))
    ends = {d: pd.Timestamp(local_day_bounds_utc(d)[1]) for d in days}
    return {d: [x for x in days if ends[x] <= cut[d]] for d in days}


def walk_forward(
    aligned: pd.DataFrame,
    policy: Policy,
    q: float,
    *,
    min_history_days: int = MIN_HISTORY_DAYS,
) -> tuple[Backtest, pd.DataFrame]:
    """Expanding-window, out-of-sample backtest. Also returns the per-day margins."""
    c = complete_rows(aligned)
    known = known_days_at_cutoff(aligned)
    tests: list[pd.DataFrame] = []
    margins: list[FloatArray] = []
    per_day: list[dict[str, Any]] = []
    skipped = 0
    for day, test in c.groupby("delivery_date", sort=True):
        history = known.get(cast(date, day), [])
        if len(history) < min_history_days:
            skipped += 1
            continue
        train = c[c["delivery_date"].isin(history)]
        m = fit_policy(train, policy, q)(test)
        tests.append(test)
        margins.append(m)
        e = test["error_mw"].to_numpy(dtype=float)
        per_day.append(
            {
                "delivery_date": day,
                "history_days": len(history),
                "mean_margin_mw": float(m.mean()),
                "coverage_pct": float(100 * (e <= m).mean()),
            }
        )
    if not tests:
        empty = c.iloc[0:0]
        return _score(empty, np.zeros(0), policy, "walk_forward", q, skipped), pd.DataFrame(per_day)
    test_all = pd.concat(tests)
    bt = _score(test_all, np.concatenate(margins), policy, "walk_forward", q, skipped)
    return bt, pd.DataFrame(per_day)


@dataclass(frozen=True)
class MarginRecommendation:
    quantile: float
    margin_mw: float | None  # flat margin fitted on the full window
    margin_mwh_per_period: float | None
    in_sample: list[Backtest]
    walk_forward: list[Backtest]

    def by(self, evaluation: str, policy: Policy) -> Backtest:
        rows = self.in_sample if evaluation == "in_sample" else self.walk_forward
        return next(b for b in rows if b.policy == policy)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def recommend(aligned: pd.DataFrame, q: float = 0.9) -> MarginRecommendation:
    """Flat P{q} margin plus all policies under both evaluations."""
    c = complete_rows(aligned)
    flat = float(np.quantile(c["error_mw"].to_numpy(dtype=float), q)) if len(c) else None
    return MarginRecommendation(
        quantile=q,
        margin_mw=flat,
        margin_mwh_per_period=flat * PERIOD_H if flat is not None else None,
        in_sample=[in_sample(aligned, p, q) for p in POLICIES],
        walk_forward=[walk_forward(aligned, p, q)[0] for p in POLICIES],
    )
