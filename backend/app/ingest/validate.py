"""Contract validation and quarantine for raw Elexon rows.

Required fields are enforced (a missing or renamed field fails the run with a
clear message, Break #5); unknown extra fields are ignored. Rows with null or
negative generation are quarantined and counted, never stored (Break #4).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.domain.timeutil import as_utc
from app.ingest.elexon_client import ElexonResponseError


class ContractError(ElexonResponseError):
    """The response no longer matches the documented schema."""


class _Row(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    dataset: str
    publish_time: AwareDatetime = Field(alias="publishTime")
    start_time: AwareDatetime = Field(alias="startTime")
    generation: float | None


class FuelhhRow(_Row):
    settlement_date: date = Field(alias="settlementDate")
    settlement_period: int = Field(alias="settlementPeriod")
    fuel_type: str = Field(alias="fuelType")


class WindforRow(_Row):
    pass


_FUELHH = TypeAdapter(list[FuelhhRow])
_WINDFOR = TypeAdapter(list[WindforRow])


@dataclass
class QualityCounters:
    rows_in: int = 0
    accepted: int = 0
    null_generation: int = 0
    negative_generation: int = 0
    non_wind: int = 0
    duplicates: int = 0
    # FUELHH only: accepted periods per settlement date (ISO date -> count)
    periods_by_day: dict[str, int] = field(default_factory=dict)
    # WINDFOR only: distinct minute-of-hour values seen (resolution check, Break #1)
    start_minutes: list[int] = field(default_factory=list)

    @property
    def rejected(self) -> int:
        return self.null_generation + self.negative_generation

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _contract(adapter: TypeAdapter[Any], raw: list[dict[str, Any]], dataset: str) -> Any:
    try:
        return adapter.validate_python(raw)
    except ValidationError as exc:
        errs = "; ".join(
            f"row {e['loc'][0]} {'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}"
            for e in exc.errors()[:3]
        )
        raise ContractError(f"{dataset} contract violation: {errs}") from exc


def _generation_ok(gen: float | None, q: QualityCounters) -> bool:
    if gen is None:
        q.null_generation += 1
        return False
    if gen < 0:
        q.negative_generation += 1
        return False
    return True


def validate_fuelhh(raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], QualityCounters]:
    """Return DB-ready actual rows, one per (start_time, fuel_type), latest publish wins."""
    q = QualityCounters(rows_in=len(raw))
    best: dict[tuple[datetime, str], dict[str, Any]] = {}
    for r in _contract(_FUELHH, raw, "FUELHH"):
        if r.fuel_type != "WIND":
            q.non_wind += 1
            continue
        if not _generation_ok(r.generation, q):
            continue
        key = (as_utc(r.start_time), r.fuel_type)
        row = {
            "start_time": key[0],
            "fuel_type": r.fuel_type,
            "settlement_date": r.settlement_date,
            "settlement_period": r.settlement_period,
            "generation_mw": float(r.generation),
            "publish_time": as_utc(r.publish_time),
        }
        if key in best:
            q.duplicates += 1
            if row["publish_time"] < best[key]["publish_time"]:
                continue
        best[key] = row
    rows = list(best.values())
    q.accepted = len(rows)
    q.periods_by_day = dict(Counter(r["settlement_date"].isoformat() for r in rows))
    return rows, q


def validate_windfor(raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], QualityCounters]:
    """Return DB-ready forecast rows, one per (start_time, publish_time), last seen wins."""
    q = QualityCounters(rows_in=len(raw))
    best: dict[tuple[datetime, datetime], dict[str, Any]] = {}
    for r in _contract(_WINDFOR, raw, "WINDFOR"):
        if not _generation_ok(r.generation, q):
            continue
        start, pub = as_utc(r.start_time), as_utc(r.publish_time)
        if (start, pub) in best:
            q.duplicates += 1
        best[(start, pub)] = {
            "start_time": start,
            "publish_time": pub,
            "generation_mw": float(r.generation),
            "lead_time_h": (start - pub).total_seconds() / 3600,
        }
    rows = list(best.values())
    q.accepted = len(rows)
    q.start_minutes = sorted({r["start_time"].minute for r in rows})
    return rows, q
