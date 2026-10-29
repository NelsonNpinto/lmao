from datetime import UTC, date, datetime, timedelta
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.ingest.chunking import date_slices, datetime_slices


def test_date_slices_inclusive_and_contiguous() -> None:
    s = date_slices(date(2025, 12, 31), date(2026, 2, 2), 7)
    assert s[0] == (date(2025, 12, 31), date(2026, 1, 6))
    assert s[-1] == (date(2026, 1, 28), date(2026, 2, 1))  # short last slice
    assert len(s) == 5


def test_date_slices_single_day() -> None:
    assert date_slices(date(2026, 1, 5), date(2026, 1, 6), 7) == [(date(2026, 1, 5),) * 2]


def test_empty_window() -> None:
    assert date_slices(date(2026, 1, 5), date(2026, 1, 5), 7) == []


def test_bad_chunk_size() -> None:
    with pytest.raises(ValueError):
        date_slices(date(2026, 1, 1), date(2026, 1, 2), 0)


def test_datetime_slices_require_tz() -> None:
    with pytest.raises(ValueError, match="timezone"):
        datetime_slices(datetime(2026, 1, 1), datetime(2026, 1, 2), 1)


@given(
    start=st.dates(date(2025, 1, 1), date(2027, 1, 1)),
    length=st.integers(0, 120),
    days=st.integers(1, 31),
)
def test_date_slices_cover_window_exactly(start: date, length: int, days: int) -> None:
    end = start + timedelta(days=length)
    covered = []
    for a, b in date_slices(start, end, days):
        assert a <= b and (b - a).days < days
        covered += [a + timedelta(days=i) for i in range((b - a).days + 1)]
    assert covered == [start + timedelta(days=i) for i in range(length)]


@given(length_h=st.integers(1, 24 * 90), days=st.integers(1, 31))
def test_datetime_slices_half_open_cover(length_h: int, days: int) -> None:
    start = datetime(2025, 12, 28, tzinfo=UTC)
    end = start + timedelta(hours=length_h)
    s = datetime_slices(start, end, days)
    assert s[0][0] == start and s[-1][1] == end
    assert all(prev[1] == nxt[0] for prev, nxt in pairwise(s))
