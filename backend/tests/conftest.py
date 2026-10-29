from __future__ import annotations

import asyncio
import gzip
import json
import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.migrate import upgrade_to_head
from app.db.session import make_engine, make_sessionmaker
from app.ingest.elexon_client import CacheMode, ElexonClient, ElexonError, FetchResult
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> list[dict[str, Any]]:
    return json.loads(gzip.decompress((FIXTURES / name).read_bytes()))  # type: ignore[no-any-return]


@pytest.fixture(scope="session")
def fuelhh_week() -> list[dict[str, Any]]:
    """FUELHH WIND, settlement dates 2026-01-05 .. 2026-01-11 (336 rows)."""
    return load_fixture("fuelhh_wind_2026-01-05_2026-01-11.json.gz")


@pytest.fixture(scope="session")
def windfor_week() -> list[dict[str, Any]]:
    """WINDFOR vintages published 2026-01-01 .. 2026-01-12."""
    return load_fixture("windfor_pub_2026-01-01_2026-01-12.json.gz")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class FakeElexonClient:
    """In-memory stand-in for Elexon with the same filtering semantics as the real API."""

    def __init__(
        self,
        fuelhh: list[dict[str, Any]],
        windfor: list[dict[str, Any]],
        *,
        fail: dict[str, ElexonError] | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.fuelhh = fuelhh
        self.windfor = windfor
        self.fail = fail or {}
        self.gate = gate
        self.calls: list[tuple[str, Any, Any]] = []

    async def _maybe_wait(self, dataset: str) -> None:
        if self.gate is not None:
            await self.gate.wait()
        if dataset in self.fail:
            raise self.fail[dataset]

    async def fetch_fuelhh(self, settlement_from: date, settlement_to: date) -> FetchResult:
        self.calls.append(("FUELHH", settlement_from, settlement_to))
        await self._maybe_wait("FUELHH")
        rows = [
            r
            for r in self.fuelhh
            if settlement_from <= date.fromisoformat(r["settlementDate"]) <= settlement_to
        ]
        return FetchResult(rows, "fake://FUELHH", datetime.now(UTC), from_cache=False)

    async def fetch_windfor(self, publish_from: datetime, publish_to: datetime) -> FetchResult:
        self.calls.append(("WINDFOR", publish_from, publish_to))
        await self._maybe_wait("WINDFOR")
        # Inclusive upper bound, like Elexon may be: boundary vintages can repeat.
        rows = [r for r in self.windfor if publish_from <= _ts(r["publishTime"]) <= publish_to]
        return FetchResult(rows, "fake://WINDFOR", datetime.now(UTC), from_cache=False)

    async def aclose(self) -> None:
        return None


# Set TEST_DATABASE_URL (postgresql+asyncpg://...) to run the suite on Postgres;
# each test then starts from an empty schema. Default: a fresh SQLite file.
PG_URL = os.environ.get("TEST_DATABASE_URL")


async def _reset_postgres(url: str) -> None:
    engine = make_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture
async def settings(tmp_path: Path) -> Settings:
    if PG_URL:
        await _reset_postgres(PG_URL)
    return Settings(
        env="test",
        data_dir=tmp_path,
        database_url=PG_URL or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        seed_on_startup=False,
        admin_token="test-token",
    )


@pytest.fixture
async def sessionmaker(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine(settings.database_url)
    await upgrade_to_head(engine)
    yield make_sessionmaker(engine)
    await engine.dispose()


def factory_for(client: ElexonClient) -> Callable[[CacheMode], ElexonClient]:
    return lambda _mode: client


@pytest.fixture
def make_client(
    settings: Settings,
) -> Callable[..., Any]:
    """Build an API client with lifespan running and an injected Elexon client."""

    def _make(elexon: ElexonClient | None = None) -> Any:
        app = create_app(settings, factory_for(elexon) if elexon else None)

        class _Ctx:
            async def __aenter__(self) -> AsyncClient:
                self._lifespan = app.router.lifespan_context(app)
                await self._lifespan.__aenter__()
                self._client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
                return self._client

            async def __aexit__(self, *exc: object) -> None:
                await self._client.aclose()
                await self._lifespan.__aexit__(None, None, None)

        return _Ctx()

    return _make
