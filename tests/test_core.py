"""Rate limiting, caching and request logging for the paid AI endpoints."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

import app.main as main_module
from app.config import AISettings
from app.core.cache import AICaches, TTLCache, cache_key
from app.core.limits import Limit, RateLimiter
from app.main import app, lifespan
from tests import test_rooms_endpoint as rooms
from tests import test_search_endpoint as search
from tests.test_catalog import build_test_settings


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# --- the limiter ----------------------------------------------------------------


def test_a_user_is_refused_past_the_limit_and_allowed_again_later() -> None:
    clock = Clock()
    limiter = RateLimiter({"search": Limit(2, 60)}, clock=clock)

    assert limiter.check("user-a", "search") is None
    assert limiter.check("user-a", "search") is None
    assert limiter.check("user-a", "search") == pytest.approx(60)

    clock.now += 30
    assert limiter.check("user-a", "search") == pytest.approx(30)
    clock.now += 30
    assert limiter.check("user-a", "search") is None


def test_users_and_buckets_are_counted_separately() -> None:
    limiter = RateLimiter(
        {"search": Limit(1, 60), "room_plan": Limit(1, 60)}, clock=Clock()
    )

    assert limiter.check("user-a", "search") is None
    assert limiter.check("user-b", "search") is None
    assert limiter.check("user-a", "room_plan") is None
    assert limiter.check("user-a", "search") is not None


def test_a_refused_request_does_not_extend_the_wait() -> None:
    clock = Clock()
    limiter = RateLimiter({"search": Limit(1, 60)}, clock=clock)
    limiter.check("user-a", "search")

    for _ in range(50):
        clock.now += 1
        limiter.check("user-a", "search")

    clock.now += 10
    assert limiter.check("user-a", "search") is None


# --- the cache ------------------------------------------------------------------


def test_entries_expire_and_the_oldest_is_evicted_first() -> None:
    clock = Clock()
    cache: TTLCache[str] = TTLCache(max_entries=2, ttl_seconds=10, clock=clock)
    cache.put("a", "1")
    cache.put("b", "2")
    cache.get("a")
    cache.put("c", "3")

    assert cache.get("b") is None  # least recently used
    assert cache.get("a") == "1"
    clock.now += 10
    assert cache.get("a") is None
    assert len(cache) == 1


def test_cache_keys_cannot_collide_by_moving_a_boundary() -> None:
    assert cache_key("ab", "c") != cache_key("a", "bc")
    assert cache_key("search", "5", "sofa") != cache_key("search", "6", "sofa")
    assert cache_key("x", b"\x00") == cache_key("x", b"\x00")


# --- the endpoints --------------------------------------------------------------


@pytest.fixture
def limited(monkeypatch: pytest.MonkeyPatch) -> RateLimiter:
    limiter = RateLimiter(
        {
            "search": Limit(1, 60),
            "room_plan": Limit(1, 60),
            "room_image": Limit(1, 3600),
        }
    )
    monkeypatch.setattr(app.state, "rate_limiter", limiter, raising=False)
    return limiter


@pytest.fixture
def cached(monkeypatch: pytest.MonkeyPatch) -> AICaches:
    caches = AICaches(ttl_seconds=600)
    monkeypatch.setattr(app.state, "ai_caches", caches, raising=False)
    return caches


@pytest.mark.anyio
async def test_search_past_the_limit_is_429_in_the_customers_language(
    limited: RateLimiter,
) -> None:
    provider = search.StubProvider(search.SOFA_DRAFT)

    async with search.search_client(search.seed_response, provider) as client:
        first = await search.post_search(client, {"query": "كنبة"})
        second = await search.post_search(client, {"query": "كنبة"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "rate_limited"
    assert "برجاء" in second.json()["detail"]["message"]
    assert int(second.headers["retry-after"]) >= 1
    # The refused request never reached the model.
    assert len(provider.calls) == 1


@pytest.mark.anyio
async def test_an_unauthenticated_request_is_401_not_counted(
    limited: RateLimiter,
) -> None:
    provider = search.StubProvider(search.SOFA_DRAFT)

    async with search.search_client(search.seed_response, provider) as client:
        anonymous = await search.post_search(
            client, {"query": "sofa"}, authenticated=False
        )
        signed_in = await search.post_search(client, {"query": "sofa"})

    assert anonymous.status_code == 401
    assert signed_in.status_code == 200


@pytest.mark.anyio
async def test_the_same_sentence_is_parsed_once(cached: AICaches) -> None:
    provider = search.StubProvider(search.SOFA_DRAFT)

    async with search.search_client(search.seed_response, provider) as client:
        first = await search.post_search(client, {"query": "a modern sofa"})
        second = await search.post_search(client, {"query": "a modern sofa"})
        other_limit = await search.post_search(
            client, {"query": "a modern sofa", "limit": 3}
        )

    assert first.json() == second.json()
    assert other_limit.status_code == 200
    # One call for the repeated sentence, one more for a different page size.
    assert len(provider.calls) == 2


@pytest.mark.anyio
async def test_a_failed_parse_is_not_cached(cached: AICaches) -> None:
    from app.ai.provider import AIProviderUnavailableError

    provider = search.StubProvider(AIProviderUnavailableError())
    async with search.search_client(search.seed_response, provider) as client:
        failed = await search.post_search(client, {"query": "sofa"})
        provider._answer = search.SOFA_DRAFT
        recovered = await search.post_search(client, {"query": "sofa"})

    assert failed.status_code == 503
    assert recovered.status_code == 200
    assert len(provider.calls) == 2


@pytest.mark.anyio
async def test_room_plans_are_limited_and_cached(
    limited: RateLimiter, cached: AICaches
) -> None:
    provider = rooms.StubProvider()

    async with rooms.room_client(rooms.seed_catalogue, provider) as client:
        body = {"query": rooms.ARABIC_ROOM}
        first = await client.post(
            "/v1/rooms/plan", json=body, headers=rooms.auth_headers()
        )
        limited_out = await client.post(
            "/v1/rooms/plan", json=body, headers=rooms.auth_headers()
        )

    assert first.status_code == 200
    assert limited_out.status_code == 429
    assert len(provider.json_calls) == 1


IMAGE_BODY: dict[str, Any] = {
    "items": [
        {"product_id": rooms.MODERN_SOFA_ID, "quantity": 1},
        {"product_id": rooms.MODERN_CHAIR_ID, "quantity": 2},
    ],
    "language": "en",
}


@pytest.mark.anyio
async def test_an_identical_preview_is_rendered_once(cached: AICaches) -> None:
    provider = rooms.StubProvider()
    fetcher = rooms.FakeFetcher()

    async with rooms.room_client(rooms.seed_catalogue, provider, fetcher) as client:
        first = await client.post(
            "/v1/rooms/image", json=IMAGE_BODY, headers=rooms.auth_headers()
        )
        second = await client.post(
            "/v1/rooms/image", json=IMAGE_BODY, headers=rooms.auth_headers()
        )
        different = await client.post(
            "/v1/rooms/image",
            json={**IMAGE_BODY, "items": IMAGE_BODY["items"][:1]},
            headers=rooms.auth_headers(),
        )

    assert first.status_code == second.status_code == different.status_code == 200
    assert first.json() == second.json()
    assert len(provider.image_calls) == 2


@pytest.mark.anyio
async def test_a_cached_preview_still_checks_every_product_for_this_caller(
    cached: AICaches,
) -> None:
    provider = rooms.StubProvider()
    fetcher = rooms.FakeFetcher()
    hidden = {"yes": False}

    def catalogue(request: httpx.Request) -> httpx.Response:
        if hidden["yes"]:
            return httpx.Response(200, json=[])
        return rooms.seed_catalogue(request)

    async with rooms.room_client(catalogue, provider, fetcher) as client:
        first = await client.post(
            "/v1/rooms/image", json=IMAGE_BODY, headers=rooms.auth_headers()
        )
        hidden["yes"] = True
        second = await client.post(
            "/v1/rooms/image", json=IMAGE_BODY, headers=rooms.auth_headers()
        )

    assert first.status_code == 200
    assert second.status_code == 404


@pytest.mark.anyio
async def test_previews_are_limited_per_hour(limited: RateLimiter) -> None:
    provider = rooms.StubProvider()

    async with rooms.room_client(
        rooms.seed_catalogue, provider, rooms.FakeFetcher()
    ) as client:
        first = await client.post(
            "/v1/rooms/image", json=IMAGE_BODY, headers=rooms.auth_headers()
        )
        second = await client.post(
            "/v1/rooms/image", json=IMAGE_BODY, headers=rooms.auth_headers()
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["message"].startswith("Too many requests")
    assert int(second.headers["retry-after"]) > 60


# --- startup --------------------------------------------------------------------

LIFESPAN_STATE = (
    "auth_gateway",
    "catalogue_gateway",
    "ai_provider",
    "reference_fetcher",
    "review_gateway",
    "ai_settings",
    "cart_reader",
    "cart_creator",
    "rate_limiter",
    "ai_caches",
)


@pytest.fixture
def isolated_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo everything the real startup attaches to the shared app.

    Without this, a real limiter and cache outlive the test and every later
    test that repeats a sentence gets a cached answer or a 429, which is how
    the first version of these tests broke twelve others.
    """

    for name in LIFESPAN_STATE:
        monkeypatch.setattr(app.state, name, None, raising=False)


@pytest.mark.anyio
async def test_the_real_startup_installs_the_limiter_and_the_caches(
    monkeypatch: pytest.MonkeyPatch, isolated_state: None
) -> None:
    monkeypatch.setattr(main_module, "load_settings", build_test_settings)
    monkeypatch.setattr(
        main_module,
        "load_ai_settings",
        lambda: AISettings(_env_file=None, RATE_LIMIT_SEARCH_PER_MINUTE=7),
    )

    async with lifespan(app):
        limiter = app.state.rate_limiter
        assert isinstance(limiter, RateLimiter)
        assert isinstance(app.state.ai_caches, AICaches)
        for _ in range(7):
            assert limiter.check("user", "search") is None
        assert limiter.check("user", "search") is not None


@pytest.mark.anyio
async def test_a_zero_ttl_turns_caching_off(
    monkeypatch: pytest.MonkeyPatch, isolated_state: None
) -> None:
    monkeypatch.setattr(main_module, "load_settings", build_test_settings)
    monkeypatch.setattr(
        main_module,
        "load_ai_settings",
        lambda: AISettings(_env_file=None, AI_CACHE_TTL_SECONDS=0),
    )

    async with lifespan(app):
        assert app.state.ai_caches is None


# --- request logging ------------------------------------------------------------


@pytest.mark.anyio
async def test_every_response_carries_a_request_id_and_one_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.requests")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/health?secret=value",
            headers={"Authorization": "Bearer do-not-log-this-token"},
        )

    request_id = response.headers["x-request-id"]
    assert len(request_id) == 32
    (line,) = [r.getMessage() for r in caplog.records if r.name == "app.requests"]
    assert f"request_id={request_id}" in line
    assert "path=/health " in line
    assert "status=200" in line
    assert "do-not-log-this-token" not in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("sent", "kept"),
    [("client-trace-0001", True), ("bad\r\nX-Injected: 1", False), ("short", False)],
)
async def test_a_client_request_id_is_kept_only_if_safe(sent: str, kept: bool) -> None:
    async def asgi_echo(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    from app.core.observability import RequestLogMiddleware

    middleware = RequestLogMiddleware(asgi_echo)
    captured: list[dict] = []

    async def send(message: dict) -> None:
        captured.append(message)

    async def receive() -> dict:
        return {"type": "http.request", "body": b""}

    await middleware(
        {
            "type": "http",
            "method": "GET",
            "path": "/x",
            "raw_path": b"/x",
            "headers": [(b"x-request-id", sent.encode("latin-1"))],
        },
        receive,
        send,
    )

    headers = dict(captured[0]["headers"])
    assert (headers[b"x-request-id"].decode() == sent) is kept


@pytest.mark.anyio
async def test_a_path_cannot_write_a_fake_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.requests")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.get("/nothing%0Arequest_id=forged status=200")

    (line,) = [r.getMessage() for r in caplog.records if r.name == "app.requests"]
    assert "\n" not in line
    assert "%0A" in line
