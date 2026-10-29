"""On-demand ingestion jobs ("Refresh from Elexon")."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.db import repositories as repo
from app.deps import RunnerDep, SessionDep, SettingsDep, require_admin
from app.ingest.runner import IngestAlreadyRunningError, IngestRequest
from app.schemas.common import Envelope, Meta
from app.schemas.ingest import IngestRunCreate, IngestRunOut

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _meta() -> Meta:
    return Meta(generated_at=datetime.now(UTC))


@router.post(
    "/runs",
    response_model=Envelope[IngestRunOut],
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
    responses={409: {"description": "A run is already in progress"}},
)
async def start_run(
    body: IngestRunCreate, session: SessionDep, runner: RunnerDep, settings: SettingsDep
) -> Envelope[IngestRunOut] | JSONResponse:
    req = IngestRequest(
        delivery_from=body.delivery_from or settings.seed_from,
        delivery_to=body.delivery_to or settings.seed_to,
        dataset=body.dataset,
        mode=body.mode,
        forecast_lookback_days=settings.forecast_lookback_days,
        chunk_days=settings.elexon_chunk_days,
    )
    try:
        run_id = await runner.start(req)
    except IngestAlreadyRunningError as exc:
        running = await repo.get_run(session, exc.run_id)
        return JSONResponse(
            status_code=409,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Ingest already running",
                "status": 409,
                "detail": str(exc),
                "run": IngestRunOut.model_validate(running).model_dump(mode="json")
                if running
                else None,
            },
        )
    run = await repo.get_run(session, run_id)
    return Envelope(data=IngestRunOut.model_validate(run), meta=_meta())


@router.get("/runs", response_model=Envelope[list[IngestRunOut]])
async def list_runs(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> Envelope[list[IngestRunOut]]:
    runs = await repo.list_runs(session, limit)
    return Envelope(data=[IngestRunOut.model_validate(r) for r in runs], meta=_meta())


@router.get("/runs/{run_id}", response_model=Envelope[IngestRunOut])
async def get_run(run_id: str, session: SessionDep) -> Envelope[IngestRunOut]:
    run = await repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Ingest run {run_id} not found")
    return Envelope(data=IngestRunOut.model_validate(run), meta=_meta())
