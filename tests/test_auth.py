"""Tests for the Supabase authentication boundary."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
import pytest

from app.auth.dependencies import get_auth_gateway
from app.auth.gateway import AuthenticationGateway, SupabaseAuthGateway
from app.config import Settings
from app.main import app

TEST_USER_ID = "12345678-1234-5678-1234-567812345678"
TEST_ACCESS_TOKEN = "test-access-token-must-not-be-returned"
TEST_PUBLISHABLE_KEY = "sb_publishable_test_key_123"

AUTHENTICATION_REQUIRED = {
    "detail": {
        "code": "authentication_required",
        "message": "Authentication is required.",
    }
}
INVALID_ACCESS_TOKEN = {
    "detail": {
        "code": "invalid_access_token",
        "message": "The access token is invalid or expired.",
    }
}
AUTHENTICATION_SERVICE_UNAVAILABLE = {
    "detail": {
        "code": "authentication_service_unavailable",
        "message": "Authentication is temporarily unavailable.",
    }
}

MockHandler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def anyio_backend() -> str:
    """Run async endpoint tests with the standard-library asyncio backend."""

    return "asyncio"


def build_test_settings() -> Settings:
    """Build valid settings without reading local or process configuration."""

    return Settings(
        SUPABASE_URL="https://test-project.supabase.co",
        SUPABASE_PUBLISHABLE_KEY=TEST_PUBLISHABLE_KEY,
        SUPABASE_AUTH_TIMEOUT_SECONDS=5.0,
        _env_file=None,
    )


@asynccontextmanager
async def api_client(handler: MockHandler) -> AsyncIterator[httpx.AsyncClient]:
    """Connect the API to a mocked Supabase transport."""

    upstream_transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=upstream_transport) as upstream_client:
        gateway = SupabaseAuthGateway(
            client=upstream_client,
            settings=build_test_settings(),
        )

        async def override_gateway() -> AuthenticationGateway:
            return gateway

        app.dependency_overrides[get_auth_gateway] = override_gateway
        try:
            api_transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=api_transport,
                base_url="http://testserver",
            ) as client:
                yield client
        finally:
            app.dependency_overrides.pop(get_auth_gateway, None)


def unexpected_upstream_call(_request: httpx.Request) -> httpx.Response:
    raise AssertionError("Supabase must not be called for malformed credentials")


def assert_authentication_required(response: httpx.Response) -> None:
    assert response.status_code == 401
    assert response.json() == AUTHENTICATION_REQUIRED
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_me_without_authorization_returns_401() -> None:
    async with api_client(unexpected_upstream_call) as client:
        response = await client.get("/v1/me")

    assert_authentication_required(response)


@pytest.mark.anyio
async def test_me_with_malformed_authorization_scheme_returns_401() -> None:
    async with api_client(unexpected_upstream_call) as client:
        response = await client.get(
            "/v1/me",
            headers={"Authorization": f"Basic {TEST_ACCESS_TOKEN}"},
        )

    assert_authentication_required(response)


@pytest.mark.anyio
async def test_me_with_empty_bearer_token_returns_401() -> None:
    async with api_client(unexpected_upstream_call) as client:
        response = await client.get(
            "/v1/me",
            headers={"Authorization": "Bearer "},
        )

    assert_authentication_required(response)


@pytest.mark.anyio
async def test_supabase_401_returns_safe_invalid_token_response() -> None:
    raw_upstream_error = "upstream says this account exists but is disabled"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == TEST_PUBLISHABLE_KEY
        assert request.headers["authorization"] == f"Bearer {TEST_ACCESS_TOKEN}"
        return httpx.Response(401, json={"message": raw_upstream_error})

    async with api_client(handler) as client:
        response = await client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 401
    assert response.json() == INVALID_ACCESS_TOKEN
    assert response.headers["www-authenticate"] == "Bearer"
    assert raw_upstream_error not in response.text
    assert TEST_ACCESS_TOKEN not in response.text


@pytest.mark.anyio
async def test_valid_supabase_user_returns_verified_identity_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == ("https://test-project.supabase.co/auth/v1/user")
        assert request.headers["apikey"] == TEST_PUBLISHABLE_KEY
        assert request.headers["authorization"] == f"Bearer {TEST_ACCESS_TOKEN}"
        return httpx.Response(
            200,
            json={
                "id": TEST_USER_ID,
                "email": "private@example.com",
                "user_metadata": {"private": True},
            },
        )

    async with api_client(handler) as client:
        response = await client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": TEST_USER_ID,
        "authenticated": True,
    }
    assert "private@example.com" not in response.text
    assert "user_metadata" not in response.text
    assert TEST_ACCESS_TOKEN not in response.text


@pytest.mark.anyio
async def test_malformed_supabase_user_uuid_is_rejected_safely() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "not-a-uuid"})

    async with api_client(handler) as client:
        response = await client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 503
    assert response.json() == AUTHENTICATION_SERVICE_UNAVAILABLE
    assert TEST_ACCESS_TOKEN not in response.text


@pytest.mark.anyio
async def test_supabase_timeout_returns_503() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Supabase timed out", request=request)

    async with api_client(handler) as client:
        response = await client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 503
    assert response.json() == AUTHENTICATION_SERVICE_UNAVAILABLE
    assert TEST_ACCESS_TOKEN not in response.text


@pytest.mark.anyio
async def test_supabase_5xx_does_not_expose_raw_error() -> None:
    raw_upstream_error = "internal Supabase diagnostic must remain private"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=raw_upstream_error)

    async with api_client(handler) as client:
        response = await client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 503
    assert response.json() == AUTHENTICATION_SERVICE_UNAVAILABLE
    assert raw_upstream_error not in response.text
    assert TEST_ACCESS_TOKEN not in response.text
