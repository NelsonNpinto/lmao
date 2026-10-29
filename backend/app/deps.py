"""FastAPI dependencies. Long-lived objects live on ``app.state`` (built in the lifespan)."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.ingest.runner import IngestRunner


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_runner(request: Request) -> IngestRunner:
    return request.app.state.runner  # type: ignore[no-any-return]


def require_admin(
    settings: Annotated[Settings, Depends(get_app_settings)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    if x_admin_token is None or not secrets.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Admin-Token")


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RunnerDep = Annotated[IngestRunner, Depends(get_runner)]
