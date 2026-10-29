"""Common query parameters: delivery window and decision cutoff."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request

from app.deps import SettingsDep
from app.domain.vintage import CutoffRule
from app.schemas.common import Meta
from app.services.analysis import AnalysisService, Window, parse_cutoff

CUTOFF_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
MAX_WINDOW_DAYS = 400


def get_analysis(request: Request) -> AnalysisService:
    return request.app.state.analysis  # type: ignore[no-any-return]


AnalysisDep = Annotated[AnalysisService, Depends(get_analysis)]


@dataclass(frozen=True)
class Scope:
    window: Window
    rule: CutoffRule
    analysis: AnalysisService

    def meta(self, completeness: float | None = None, notes: list[str] | None = None) -> Meta:
        w = self.window
        extra = list(notes or [])
        if w.clamped:
            extra.append(
                f"Window trimmed to available data: {w.day_from} to {w.day_to} (exclusive)."
            )
        if not w.has_data:
            extra.append("No data in the requested window.")
        return Meta(
            generated_at=datetime.now(UTC),
            window_from=w.day_from,
            window_to=w.day_to,
            requested_from=w.requested_from,
            requested_to=w.requested_to,
            cutoff=self.rule.local_time.strftime("%H:%M"),
            cutoff_days_before=self.rule.days_before,
            completeness=completeness if w.has_data else 0.0,
            clamped=w.clamped,
            data_version=self.analysis.version,
            notes=extra,
        )


def validate_window(from_: date | None, to: date | None) -> None:
    if from_ and to:
        if from_ >= to:
            raise HTTPException(422, "'from' must be before 'to' (half-open window)")
        if (to - from_).days > MAX_WINDOW_DAYS:
            raise HTTPException(422, f"window may not exceed {MAX_WINDOW_DAYS} days")


async def scope(
    settings: SettingsDep,
    analysis: AnalysisDep,
    from_: Annotated[
        date | None,
        Query(alias="from", description="First UK delivery day (default: study window)"),
    ] = None,
    to: Annotated[date | None, Query(description="Exclusive end delivery day")] = None,
    cutoff: Annotated[
        str | None, Query(pattern=CUTOFF_PATTERN, description="UK local HH:MM, default 09:00")
    ] = None,
    days_before: Annotated[
        int | None, Query(ge=1, le=2, description="Cutoff on D-1 or D-2 (default 1)")
    ] = None,
) -> Scope:
    validate_window(from_, to)
    rule = CutoffRule(
        parse_cutoff(cutoff) if cutoff else settings.cutoff_local,
        days_before or settings.cutoff_days_before,
    )
    return Scope(await analysis.window(from_, to), rule, analysis)


ScopeDep = Annotated[Scope, Depends(scope)]
