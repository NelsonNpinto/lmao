"""Liveness, readiness and build/data metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from app.db import repositories as repo
from app.deps import RunnerDep, SessionDep, SettingsDep
from app.schemas.common import Envelope, Meta
from app.schemas.ingest import IngestRunOut

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    detail: str | None = None


class Coverage(BaseModel):
    actual_rows: int
    actual_from: datetime | None
    actual_to: datetime | None
    actual_revisions: int
    forecast_rows: int
    forecast_vintages: int
    forecast_published_from: datetime | None
    forecast_published_to: datetime | None


class AppMeta(BaseModel):
    version: str
    git_sha: str
    env: str
    data_version: int
    ingest_running: str | None
    defaults: dict[str, str | float | list[float]]
    coverage: Coverage
    last_ingest: IngestRunOut | None


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health(status="ok")


@router.get("/ready", response_model=Health, responses={503: {"model": Health}})
async def ready(session: SessionDep) -> Health | JSONResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=Health(status="unavailable", detail=str(exc)[:200]).model_dump(),
        )
    return Health(status="ready")


@router.get("/meta", response_model=Envelope[AppMeta])
async def meta(
    request: Request, session: SessionDep, settings: SettingsDep, runner: RunnerDep
) -> Envelope[AppMeta]:
    cov = await repo.coverage(session)
    last = cov.pop("last_run")
    return Envelope(
        data=AppMeta(
            version=__version__,
            git_sha=settings.git_sha,
            env=settings.env,
            data_version=request.app.state.data_version,
            ingest_running=runner.running_id,
            defaults={
                "study_from": settings.study_from.isoformat(),
                "study_to": settings.study_to.isoformat(),
                "cutoff": settings.cutoff_local.strftime("%H:%M"),
                "margin_quantile": settings.margin_quantile,
                "lead_time_buckets_h": settings.lead_time_buckets_h,
            },
            coverage=Coverage(**cov),
            last_ingest=IngestRunOut.model_validate(last) if last else None,
        ),
        meta=Meta(generated_at=datetime.now(UTC), data_version=request.app.state.data_version),
    )
