"""UK settlement-day time arithmetic. Pure functions, no I/O.

Everything is stored in UTC; UK local time only appears when turning a
delivery date or a cutoff like "09:00 on D-1" into UTC instants. Periods are
derived from UTC timestamps, never from period numbers, so clock-change days
(46 or 50 periods) fall out naturally.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
PERIOD = timedelta(minutes=30)


def local_day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    """UTC instants of local midnight at the start of ``d`` and of the next day."""
    start = datetime.combine(d, time(0), tzinfo=UK).astimezone(UTC)
    end = datetime.combine(d + timedelta(days=1), time(0), tzinfo=UK).astimezone(UTC)
    return start, end


def periods_in_local_day(d: date) -> int:
    """48 normally, 46 on the spring clock change, 50 on the autumn one."""
    start, end = local_day_bounds_utc(d)
    return int((end - start) / PERIOD)


def cutoff_utc(delivery_day: date, cutoff_local: time, days_before: int = 1) -> datetime:
    """UTC instant of the decision cutoff for ``delivery_day`` (UK local time on D-n)."""
    decision_day = delivery_day - timedelta(days=days_before)
    return datetime.combine(decision_day, cutoff_local, tzinfo=UK).astimezone(UTC)


def as_utc(dt: datetime) -> datetime:
    """Return ``dt`` in UTC; naive datetimes are rejected rather than guessed."""
    if dt.tzinfo is None:
        raise ValueError(f"naive datetime not allowed: {dt!r}")
    return dt.astimezone(UTC)
