"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from http import HTTPStatus

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.v1 import api_router
from app.config import Settings, get_settings
from app.db import repositories as repo
from app.db.migrate import upgrade_to_head
from app.db.models import IngestRun
from app.db.session import make_engine, make_sessionmaker
from app.ingest.elexon_client import CacheMode, ElexonClient, HttpElexonClient
from app.ingest.runner import ClientFactory, IngestRequest, IngestRunner
from app.logging import configure_logging, get_logger
from app.schemas.common import Problem
from app.services.analysis import AnalysisService
from app.services.response_cache import ResponseCache

log = get_logger(__name__)

CACHEABLE_PREFIXES = (
    "/api/v1/series",
    "/api/v1/metrics",
    "/api/v1/findings",
    "/api/v1/procurement",
    "/api/v1/days",
    "/api/v1/replay",
    "/api/v1/export",
)


def http_client_factory(s: Settings) -> ClientFactory:
    def make(mode: CacheMode) -> ElexonClient:
        return HttpElexonClient(
            s.elexon_base_url,
            timeout_s=s.elexon_timeout_s,
            max_retries=s.elexon_max_retries,
            cache_dir=s.raw_cache_dir,
            cache_mode=mode,
        )

    return make


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s: Settings = app.state.settings
    log.info("startup", env=s.env, version=__version__, git_sha=s.git_sha)
    if s.database_url.startswith("sqlite"):
        s.data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(s.database_url)
    await upgrade_to_head(engine)
    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as session:
        if n := await repo.fail_interrupted_runs(session):
            log.warning("ingest_runs_interrupted", count=n)
        await session.commit()
        needs_seed = not await repo.has_completed_run(session)

    app.state.data_version = 0

    def bump_version(run: IngestRun) -> None:
        # Cache keys include data_version, so analytics recompute after new data.
        if run.rows_upserted:
            app.state.data_version += 1
            # Re-warm the default view so the first visitor after new data is fast.
            app.state.warm_task = asyncio.create_task(app.state.analysis.warm())

    runner = IngestRunner(
        sessionmaker,
        app.state.client_factory or http_client_factory(s),
        concurrency=s.elexon_concurrency,
        on_complete=bump_version,
    )
    app.state.sessionmaker = sessionmaker
    app.state.runner = runner
    app.state.analysis = AnalysisService(sessionmaker, s, lambda: app.state.data_version)

    if s.seed_on_startup and needs_seed:
        # read_through: uses the committed raw cache if present, so the demo boots
        # without Elexon; any missing slice is fetched live.
        log.info("seed_on_startup", delivery_from=str(s.seed_from), delivery_to=str(s.seed_to))
        await runner.start(
            IngestRequest(
                delivery_from=s.seed_from,
                delivery_to=s.seed_to,
                mode="read_through",
                forecast_lookback_days=s.forecast_lookback_days,
                chunk_days=s.elexon_chunk_days,
            )
        )
    else:
        app.state.warm_task = asyncio.create_task(app.state.analysis.warm())
    yield
    await runner.shutdown()
    await engine.dispose()
    log.info("shutdown")


def _problem(request: Request, status: int, title: str, detail: str | None) -> JSONResponse:
    body = Problem(
        title=title,
        status=status,
        detail=detail,
        instance=str(request.url.path),
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        media_type="application/problem+json",
    )


def create_app(
    settings: Settings | None = None, client_factory: ClientFactory | None = None
) -> FastAPI:
    s = settings or get_settings()
    configure_logging(s.log_level, json=s.env != "dev")

    app = FastAPI(
        title="WindSight API",
        version=__version__,
        description="As-of GB wind forecast accuracy and procurement margins from Elexon BMRS.",
        lifespan=lifespan,
    )
    app.state.settings = s
    app.state.client_factory = client_factory
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "ETag"],
    )

    app.add_middleware(GZipMiddleware, minimum_size=1024)

    response_cache = ResponseCache(max_bytes=64 * 1024 * 1024)
    # Build salt: new code (new process) never matches an ETag issued by old code.
    build = hashlib.sha1(
        f"{__version__}-{s.git_sha}-{time.time_ns()}".encode(), usedforsecurity=False
    ).hexdigest()[:8]

    @app.middleware("http")
    async def conditional_get(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Weak ETag and response cache keyed on (data_version, URL) (Break #18).

        Analytics responses are a pure function of the data version and the
        query, so a matching If-None-Match short-circuits to 304, and a repeat
        request is served from memory without recomputing or re-serialising.
        A new data version changes every key, so nothing stale is served.
        """
        path = request.url.path
        if request.method != "GET" or not path.startswith(CACHEABLE_PREFIXES):
            return await call_next(request)
        version = getattr(request.app.state, "data_version", 0)
        digest = hashlib.sha1(str(request.url).encode(), usedforsecurity=False).hexdigest()[:16]
        etag = f'W/"{build}-v{version}-{digest}"'
        # no-cache = always revalidate: a 304 is cheap, and a deploy that changes
        # a response shape can never be masked by a browser-cached copy.
        headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
        if request.headers.get("If-None-Match") == etag:
            return Response(status_code=304, headers=headers)
        gzip_ok = "gzip" in request.headers.get("Accept-Encoding", "")
        key = (etag, gzip_ok)
        if (hit := response_cache.get(key)) is not None:
            body, cached_headers = hit
            return Response(body, status_code=200, headers=cached_headers)
        response = await call_next(request)
        if response.status_code != 200:
            return response
        response.headers.update(headers)
        if isinstance(response, StreamingResponse) and "content-length" in response.headers:
            # call_next wraps every response as a stream; ones with a known length
            # are fully built already, so buffer and cache them. True streams
            # (very large CSV exports) pass through untouched.
            chunks = [c async for c in response.body_iterator]
            body = b"".join(c.encode() if isinstance(c, str) else bytes(c) for c in chunks)
            out_headers = {k: v for k, v in response.headers.items() if k != "content-length"}
            response_cache.put(key, body, out_headers)
            return Response(body, status_code=200, headers=out_headers)
        return response

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        structlog.contextvars.bind_contextvars(request_id=rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        ms = round((time.perf_counter() - t0) * 1000, 1)
        response.headers["X-Request-ID"] = rid
        log.info(
            "request",
            request_id=rid,
            route=request.url.path,
            status=response.status_code,
            latency_ms=ms,
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return _problem(request, 422, "Invalid request", detail)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        title = HTTPStatus(exc.status_code).phrase
        return _problem(request, exc.status_code, title, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error=str(exc))
        return _problem(request, 500, "Internal server error", None)

    app.include_router(api_router)
    return app


app = create_app()
