from typing import Any


async def test_health_ok(make_client: Any) -> None:
    async with make_client() as c:
        r = await c.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "X-Request-ID" in r.headers


async def test_ready_checks_db(make_client: Any) -> None:
    async with make_client() as c:
        r = await c.get("/api/v1/ready")
    assert r.json() == {"status": "ready", "detail": None}


async def test_meta_envelope_and_empty_coverage(make_client: Any) -> None:
    async with make_client() as c:
        r = await c.get("/api/v1/meta")
    body = r.json()
    assert set(body) == {"data", "meta"}
    assert body["data"]["defaults"]["cutoff"] == "09:00"
    assert body["data"]["coverage"]["actual_rows"] == 0
    assert body["data"]["last_ingest"] is None


async def test_unknown_route_is_problem_json(make_client: Any) -> None:
    async with make_client() as c:
        r = await c.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 404


async def test_request_id_is_echoed(make_client: Any) -> None:
    async with make_client() as c:
        r = await c.get("/api/v1/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
