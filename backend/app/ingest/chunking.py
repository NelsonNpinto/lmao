"""Split ingest windows into bounded request slices."""

from __future__ import annotations

from datetime import date, datetime, timedelta


def date_slices(start: date, end_exclusive: date, days: int) -> list[tuple[date, date]]:
    """Inclusive ``(from, to)`` date pairs covering ``[start, end_exclusive)``.

    Elexon's settlementDateFrom/To are both inclusive, so each pair is
    inclusive and consecutive pairs never overlap.
    """
    if days < 1:
        raise ValueError("days must be >= 1")
    out: list[tuple[date, date]] = []
    cur = start
    while cur < end_exclusive:
        nxt = min(cur + timedelta(days=days), end_exclusive)
        out.append((cur, nxt - timedelta(days=1)))
        cur = nxt
    return out


def datetime_slices(
    start: datetime, end_exclusive: datetime, days: int
) -> list[tuple[datetime, datetime]]:
    """Half-open ``[from, to)`` pairs covering ``[start, end_exclusive)``.

    Elexon may treat publishDateTimeTo as inclusive, so a vintage published
    exactly on a boundary can appear in two slices; the runner de-duplicates
    on the natural key before upserting.
    """
    if days < 1:
        raise ValueError("days must be >= 1")
    if start.tzinfo is None or end_exclusive.tzinfo is None:
        raise ValueError("datetimes must be timezone-aware")
    out: list[tuple[datetime, datetime]] = []
    cur = start
    step = timedelta(days=days)
    while cur < end_exclusive:
        nxt = min(cur + step, end_exclusive)
        out.append((cur, nxt))
        cur = nxt
    return out
