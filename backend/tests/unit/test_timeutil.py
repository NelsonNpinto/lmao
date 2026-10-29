from datetime import UTC, date, datetime, time

import pytest

from app.domain.timeutil import as_utc, cutoff_utc, local_day_bounds_utc, periods_in_local_day


@pytest.mark.parametrize(
    ("d", "n"),
    [(date(2026, 1, 15), 48), (date(2026, 3, 29), 46), (date(2026, 10, 25), 50)],
)
def test_periods_per_local_day(d: date, n: int) -> None:
    assert periods_in_local_day(d) == n


def test_day_bounds_in_bst() -> None:
    start, end = local_day_bounds_utc(date(2026, 6, 1))
    assert start == datetime(2026, 5, 31, 23, 0, tzinfo=UTC)
    assert end == datetime(2026, 6, 1, 23, 0, tzinfo=UTC)


def test_cutoff_is_uk_local_not_utc() -> None:
    # January: GMT, so 09:00 UK == 09:00Z on D-1.
    assert cutoff_utc(date(2026, 1, 10), time(9)) == datetime(2026, 1, 9, 9, tzinfo=UTC)
    # Delivery 30 Mar, decision 29 Mar (first BST day): 09:00 BST == 08:00Z (Break #11).
    assert cutoff_utc(date(2026, 3, 30), time(9)) == datetime(2026, 3, 29, 8, tzinfo=UTC)
    # Delivery 29 Mar, decision 28 Mar (still GMT).
    assert cutoff_utc(date(2026, 3, 29), time(9)) == datetime(2026, 3, 28, 9, tzinfo=UTC)
    # D-2 cutoff.
    assert cutoff_utc(date(2026, 1, 10), time(23), 2) == datetime(2026, 1, 8, 23, tzinfo=UTC)


def test_as_utc_rejects_naive() -> None:
    with pytest.raises(ValueError, match="naive"):
        as_utc(datetime(2026, 1, 1))
