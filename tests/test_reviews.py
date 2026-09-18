"""GET /v1/reviews/public: anonymous, seven safe columns, nothing identifying."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
import pytest

from app.main import app
from app.reviews.gateway import PUBLIC_REVIEW_COLUMNS, SupabaseReviewGateway
from app.reviews.router import get_review_gateway
from tests.test_catalog import TEST_PUBLISHABLE_KEY, build_test_settings

PRODUCT = "7a000000-0000-4000-8000-000000000017"
SELLER = "7b000000-0000-4000-8000-000000000001"
OTHER = "7a000000-0000-4000-8000-000000000019"


def review(n: int, **overrides) -> dict:
    row = {
        "id": f"7c000000-0000-4000-8000-{n:012d}",
        "target_kind": "product",
        "target_product_id": PRODUCT,
        "target_marketplace_party_id": None,
        "rating": 4,
        "comment": "مريحة جدا",
        "created_at": "2026-09-10T12:00:00+00:00",
    }
    return row | overrides


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@asynccontextmanager
async def review_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        gateway = SupabaseReviewGateway(client=upstream, settings=build_test_settings())

        async def override() -> SupabaseReviewGateway:
            return gateway

        app.dependency_overrides[get_review_gateway] = override
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                yield client
        finally:
            app.dependency_overrides.pop(get_review_gateway, None)


@pytest.mark.anyio
async def test_reviews_are_read_as_anon_with_only_the_safe_columns() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[review(1), review(2, rating=5)])

    async with review_client(handler) as client:
        response = await client.get(f"/v1/reviews/public?product_id={PRODUCT}")

    assert response.status_code == 200
    payload = response.json()
    assert [item["rating"] for item in payload["items"]] == [4, 5]
    assert payload["items"][0]["comment"] == "مريحة جدا"
    assert payload["has_more"] is False

    (request,) = seen
    # Anonymous: the publishable key and no user token.
    assert request.headers["apikey"] == TEST_PUBLISHABLE_KEY
    assert "authorization" not in request.headers
    params = request.url.params
    assert params["select"] == PUBLIC_REVIEW_COLUMNS
    assert params["target_kind"] == "eq.product"
    assert params["target_product_id"] == f"eq.{PRODUCT}"
    # The two columns anon loses in 3.2C are never named, not even in a filter.
    assert "customer_profile_id" not in str(request.url)
    assert "target_service_request_id" not in str(request.url)


@pytest.mark.anyio
async def test_nothing_identifying_the_reviewer_is_returned() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[review(1)])

    async with review_client(handler) as client:
        response = await client.get(f"/v1/reviews/public?product_id={PRODUCT}")

    (item,) = response.json()["items"]
    assert set(item) == {
        "id",
        "target_kind",
        "product_id",
        "seller_id",
        "rating",
        "comment",
        "created_at",
    }


@pytest.mark.anyio
async def test_seller_reviews_filter_on_the_seller() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        row = review(
            1,
            target_kind="marketplace_party",
            target_product_id=None,
            target_marketplace_party_id=SELLER,
        )
        return httpx.Response(200, json=[row])

    async with review_client(handler) as client:
        response = await client.get(f"/v1/reviews/public?seller_id={SELLER}")

    assert response.json()["items"][0]["seller_id"] == SELLER
    assert seen[0].url.params["target_kind"] == "eq.marketplace_party"
    assert seen[0].url.params["target_marketplace_party_id"] == f"eq.{SELLER}"


@pytest.mark.anyio
async def test_rows_for_another_target_are_dropped_not_shown() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                review(1),
                review(2, target_product_id=OTHER),
                review(3, target_marketplace_party_id=SELLER),
                review(4, target_kind="service_request"),
            ],
        )

    async with review_client(handler) as client:
        response = await client.get(f"/v1/reviews/public?product_id={PRODUCT}")

    assert [i["id"][-1] for i in response.json()["items"]] == ["1"]


@pytest.mark.anyio
async def test_a_full_page_reports_more() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["limit"] == "3"
        assert request.url.params["offset"] == "4"
        return httpx.Response(200, json=[review(n) for n in range(3)])

    async with review_client(handler) as client:
        response = await client.get(
            f"/v1/reviews/public?product_id={PRODUCT}&limit=2&offset=4"
        )

    payload = response.json()
    assert len(payload["items"]) == 2
    assert payload["has_more"] is True


@pytest.mark.anyio
@pytest.mark.parametrize(
    "query",
    ["", f"product_id={PRODUCT}&seller_id={SELLER}", "product_id=nope", "limit=0"],
)
async def test_unusable_requests_are_rejected(query: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Supabase must not be called")

    async with review_client(handler) as client:
        response = await client.get(f"/v1/reviews/public?{query}")

    assert response.status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("upstream", "status", "code"),
    [
        (503, 503, "reviews_unavailable"),
        (401, 502, "reviews_upstream_error"),
        (200, 502, "reviews_upstream_error"),  # unparseable body
    ],
)
async def test_upstream_failures_are_mapped(upstream: int, status: int, code: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream, json={"not": "a list"})

    async with review_client(handler) as client:
        response = await client.get(f"/v1/reviews/public?product_id={PRODUCT}")

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
