from datetime import UTC, datetime
from typing import Any

import pytest

from app.ingest.validate import ContractError, validate_fuelhh, validate_windfor


def fuel(sp: int, gen: Any, pub: str = "2026-01-05T00:30:00Z", **kw: Any) -> dict[str, Any]:
    start = datetime(2026, 1, 5, tzinfo=UTC).replace(hour=(sp - 1) // 2, minute=30 * ((sp - 1) % 2))
    return {
        "dataset": "FUELHH",
        "publishTime": pub,
        "startTime": start.isoformat().replace("+00:00", "Z"),
        "settlementDate": "2026-01-05",
        "settlementPeriod": sp,
        "fuelType": "WIND",
        "generation": gen,
        **kw,
    }


def test_quarantines_null_and_negative_and_drops_non_wind() -> None:
    rows, q = validate_fuelhh(
        [fuel(1, 100), fuel(2, None), fuel(3, -5), fuel(4, 200, fuelType="CCGT")]
    )
    assert [r["settlement_period"] for r in rows] == [1]
    assert (q.null_generation, q.negative_generation, q.non_wind) == (1, 1, 1)
    assert q.rejected == 2
    assert q.periods_by_day == {"2026-01-05": 1}


def test_duplicate_actual_keeps_latest_publish() -> None:
    rows, q = validate_fuelhh(
        [fuel(1, 100, "2026-01-05T01:00:00Z"), fuel(1, 90, "2026-01-05T00:30:00Z")]
    )
    assert len(rows) == 1 and rows[0]["generation_mw"] == 100
    assert q.duplicates == 1


def test_timestamps_are_aware_utc() -> None:
    rows, _ = validate_fuelhh([fuel(1, 100)])
    assert rows[0]["start_time"] == datetime(2026, 1, 5, tzinfo=UTC)
    assert rows[0]["start_time"].tzinfo is not None


def test_extra_fields_ignored_missing_fields_fail_loudly() -> None:
    validate_fuelhh([fuel(1, 100, newField="x")])
    bad = fuel(1, 100)
    del bad["startTime"]
    with pytest.raises(ContractError, match=r"FUELHH contract violation: row 0 startTime"):
        validate_fuelhh([bad])


def test_windfor_dedup_lead_time_and_resolution() -> None:
    v = {
        "dataset": "WINDFOR",
        "publishTime": "2026-01-04T07:30:00Z",
        "startTime": "2026-01-05T09:00:00Z",
        "generation": 12000,
    }
    rows, q = validate_windfor([v, {**v, "generation": 12500}, {**v, "generation": None}])
    assert len(rows) == 1 and rows[0]["generation_mw"] == 12500  # last seen wins
    assert rows[0]["lead_time_h"] == pytest.approx(25.5)
    assert q.duplicates == 1 and q.null_generation == 1
    assert q.start_minutes == [0]
