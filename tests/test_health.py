"""Tests for the health endpoint."""

from collections.abc import AsyncIterator

import httpx
import pytest

from app.main import app


@pytest.fixture
def anyio_backend() -> str:
    """Run async endpoint tests with the standard-library asyncio backend."""

    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide an HTTP client connected directly to the ASGI application."""

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        yield test_client


@pytest.mark.anyio
async def test_health_returns_expected_response(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "furniture-ai-api",
        "version": "0.1.0",
    }


@pytest.mark.anyio
async def test_unknown_route_returns_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get("/unknown-route")

    assert response.status_code == 404
