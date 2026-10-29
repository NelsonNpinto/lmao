"""Naive persistence baseline: tomorrow's wind = today's, same settlement period."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from app.domain.timeutil import local_day_bounds_utc, periods_in_local_day
from app.domain.vintage import HALF_HOUR, local_dates


def date_and_period(start_times: pd.Series) -> tuple[pd.Series, pd.Series]:
    """UK delivery date and 1-based settlement period, derived from UTC (Break #10)."""
    days = local_dates(start_times)
    day_start = pd.to_datetime(
        days.map({d: local_day_bounds_utc(d)[0] for d in pd.unique(days)}), utc=True
    )
    periods = ((start_times - day_start) / HALF_HOUR).astype(int) + 1
    return days, periods


def persistence_baseline(actuals: pd.DataFrame) -> pd.DataFrame:
    """For every actual at (day d, period p) emit a forecast for (d + 1, p).

    Returns ``start_time`` (the target half-hour) and ``persistence_mw``.
    Periods that do not exist on the target day (49-50 into a 48-period day)
    are dropped; target periods with no source (47-48 after a 46-period day)
    simply have no row.
    """
    days, periods = date_and_period(actuals["start_time"])
    src = pd.DataFrame(
        {
            "day": days + timedelta(days=1),
            "period": periods,
            "persistence_mw": actuals["generation_mw"],
        }
    )
    limit = src["day"].map({d: periods_in_local_day(d) for d in pd.unique(src["day"])})
    src = src[src["period"] <= limit]
    starts: dict[date, pd.Timestamp] = {
        d: pd.Timestamp(local_day_bounds_utc(d)[0]) for d in pd.unique(src["day"])
    }
    src["start_time"] = (
        pd.to_datetime(src["day"].map(starts), utc=True) + (src["period"] - 1) * HALF_HOUR
    )
    return src[["start_time", "persistence_mw"]].reset_index(drop=True)
