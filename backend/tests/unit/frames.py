"""Tiny builders for hand-checkable aligned frames."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from app.domain.align import ALIGNED_COLUMNS


def ts(s: str) -> pd.Timestamp:
    return (
        pd.Timestamp(s).tz_convert("UTC") if pd.Timestamp(s).tzinfo else pd.Timestamp(s, tz="UTC")
    )


def aligned(
    actual: Sequence[float],
    error: Sequence[float],
    persistence_error: Sequence[float] | None = None,
    *,
    day: date = date(2026, 1, 10),
    rows_per_day: int | None = None,
    lead_time_h: float = 20.0,
) -> pd.DataFrame:
    """Aligned frame with forecast = actual + error, consecutive half-hours from ``day``.

    ``rows_per_day`` spreads rows across consecutive days (for bootstrap / walk-forward).
    """
    n = len(actual)
    a = np.asarray(actual, dtype=float)
    e = np.asarray(error, dtype=float)
    per = rows_per_day or n
    days = [day + timedelta(days=i // per) for i in range(n)]
    starts = [
        datetime.combine(d, datetime.min.time(), tzinfo=UTC) + timedelta(minutes=30 * (i % per))
        for i, d in enumerate(days)
    ]
    df = pd.DataFrame({"start_time": pd.to_datetime(starts, utc=True)})
    df["delivery_date"] = days
    df["period"] = [i % per + 1 for i in range(n)]
    df["hour_of_day"] = df["start_time"].dt.hour
    df["weekday"] = df["start_time"].dt.day_of_week
    df["cutoff"] = pd.to_datetime(
        [
            datetime.combine(d - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
            + timedelta(hours=9)
            for d in days
        ],
        utc=True,
    )
    df["publish_time"] = df["cutoff"] - pd.Timedelta(minutes=90)
    df["forecast_hour"] = df["start_time"].dt.floor("h")
    df["lead_time_h"] = lead_time_h
    df["vintage_age_h"] = 1.5
    df["stale"] = False
    df["forecast_mw"] = a + e
    df["actual_mw"] = a
    if persistence_error is None:
        df["persistence_mw"] = np.nan
    else:
        df["persistence_mw"] = a + np.asarray(persistence_error, dtype=float)
    df["error_mw"] = df["forecast_mw"] - df["actual_mw"]
    df["persistence_error_mw"] = df["persistence_mw"] - df["actual_mw"]
    df["has_forecast"] = True
    df["has_actual"] = True
    return df[ALIGNED_COLUMNS]
