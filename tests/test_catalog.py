"""Tests for the authenticated read-only Supabase catalogue."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.auth.dependencies import get_auth_gateway
from app.auth.gateway import AuthenticationGateway
from app.auth.models import AuthenticatedUser
from app.catalog.dependencies import get_catalogue_gateway
from app.catalog.gateway import (
    CATALOG_SELECT,
    CatalogueGateway,
    SupabaseCatalogueGateway,
)
from app.config import Settings
from app.main import app

TEST_ACCESS_TOKEN = "catalog-access-token-must-not-be-returned"
TEST_PUBLISHABLE_KEY = "sb_publishable_catalog_test_key"
TEST_USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PRODUCT_ID = "20000000-0000-4000-8000-000000000000"
LOWER_PRODUCT_ID = "10000000-0000-4000-8000-000000000000"
CATEGORY_ID = "30000000-0000-4000-8000-000000000000"
SELLER_ID = "40000000-0000-4000-8000-000000000000"
COLOR_ONE_ID = "51000000-0000-4000-8000-000000000000"
COLOR_TWO_ID = "52000000-0000-4000-8000-000000000000"
COLOR_OUT_OF_STOCK_ID = "50000000-0000-4000-8000-000000000000"
IMAGE_ONE_ID = "61000000-0000-4000-8000-000000000000"
IMAGE_TWO_ID = "62000000-0000-4000-8000-000000000000"
IMAGE_THREE_ID = "63000000-0000-4000-8000-000000000000"

AUTHENTICATION_REQUIRED = {
    "detail": {
        "code": "authentication_required",
        "message": "Authentication is required.",
    }
}
CATALOGUE_UPSTREAM_ERROR = {
    "detail": {
        "code": "catalogue_upstream_error",
        "message": "The catalogue could not be loaded.",
    }
}
CATALOGUE_SERVICE_UNAVAILABLE = {
    "detail": {
        "code": "catalogue_service_unavailable",
        "message": "The catalogue is temporarily unavailable.",
    }
}
PRODUCT_NOT_FOUND = {
    "detail": {
        "code": "product_not_found",
        "message": "The product was not found.",
    }
}

MockHandler = Callable[[httpx.Request], httpx.Response]


class VerifiedAuthGateway:
    """Deterministic Phase 2 boundary used before the catalogue request."""

    async def authenticate(self, access_token: str) -> AuthenticatedUser:
        assert access_token == TEST_ACCESS_TOKEN
        return AuthenticatedUser(user_id=TEST_USER_ID)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def build_test_settings() -> Settings:
    return Settings(
        SUPABASE_URL="https://test-project.supabase.co",
        SUPABASE_PUBLISHABLE_KEY=TEST_PUBLISHABLE_KEY,
        SUPABASE_AUTH_TIMEOUT_SECONDS=5.0,
        _env_file=None,
    )


@asynccontextmanager
async def catalogue_client(handler: MockHandler) -> AsyncIterator[httpx.AsyncClient]:
    """Attach a real catalogue gateway to a mock-only HTTP transport."""

    upstream_transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=upstream_transport) as upstream_client:
        catalogue_gateway = SupabaseCatalogueGateway(
            client=upstream_client,
            settings=build_test_settings(),
        )
        auth_gateway = VerifiedAuthGateway()

        async def override_auth_gateway() -> AuthenticationGateway:
            return auth_gateway

        async def override_catalogue_gateway() -> CatalogueGateway:
            return catalogue_gateway

        app.dependency_overrides[get_auth_gateway] = override_auth_gateway
        app.dependency_overrides[get_catalogue_gateway] = override_catalogue_gateway
        try:
            api_transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=api_transport,
                base_url="http://testserver",
            ) as client:
                yield client
        finally:
            app.dependency_overrides.pop(get_auth_gateway, None)
            app.dependency_overrides.pop(get_catalogue_gateway, None)


def product_payload(
    product_id: str = PRODUCT_ID,
    *,
    name: str = "Oak Lounge Chair",
) -> dict[str, Any]:
    return {
        "id": product_id,
        "name": name,
        "description": "Solid oak frame with linen upholstery.",
        "price": 799.99,
        "discount_price": 749.5,
        "width": 80.5,
        "height": 90,
        "depth": 75,
        "weight": 12.25,
        "materials": ["oak", "linen"],
        "lifecycle_state": "published",
        "category": {
            "id": CATEGORY_ID,
            "name": "Chairs",
            "is_active": True,
        },
        "seller": {
            "id": SELLER_ID,
            "business_name": "Artisan Furniture",
            "approval_state": "approved",
        },
        "colors": [
            {
                "id": COLOR_TWO_ID,
                "color_value": "Walnut",
                "stock_quantity": 3,
                "display_order": 2,
            },
            {
                "id": COLOR_OUT_OF_STOCK_ID,
                "color_value": "Natural",
                "stock_quantity": 0,
                "display_order": 0,
            },
            {
                "id": COLOR_ONE_ID,
                "color_value": "Oak",
                "stock_quantity": 5,
                "display_order": 2,
            },
        ],
        "images": [
            {
                "id": IMAGE_THREE_ID,
                "image_url": "https://images.example.com/three.jpg",
                "is_primary": True,
                "display_order": 2,
                "product_color_id": COLOR_TWO_ID,
            },
            {
                "id": IMAGE_TWO_ID,
                "image_url": "https://images.example.com/two.jpg",
                "is_primary": False,
                "display_order": 0,
                "product_color_id": None,
            },
            {
                "id": IMAGE_ONE_ID,
                "image_url": "https://images.example.com/one.jpg",
                "is_primary": True,
                "display_order": 2,
                "product_color_id": COLOR_ONE_ID,
            },
        ],
        "enrichment_assignments": [
            {
                "id": "73000000-0000-4000-8000-000000000000",
                "confirmation_state": "party_confirmed",
                "value": "contemporary",
                "attribute": {
                    "id": "83000000-0000-4000-8000-000000000000",
                    "kind": "style",
                },
            },
            {
                "id": "71000000-0000-4000-8000-000000000000",
                "confirmation_state": "ai_proposed",
                "value": "private AI suggestion",
                "attribute": {
                    "id": "81000000-0000-4000-8000-000000000000",
                    "kind": "material_hint",
                },
            },
            {
                "id": "72000000-0000-4000-8000-000000000000",
                "confirmation_state": "party_confirmed",
                "value": "classic",
                "attribute": {
                    "id": "82000000-0000-4000-8000-000000000000",
                    "kind": "style",
                },
            },
            {
                "id": "70000000-0000-4000-8000-000000000000",
                "confirmation_state": "party_confirmed",
                "value": "warm",
                "attribute": {
                    "id": "80000000-0000-4000-8000-000000000000",
                    "kind": "color_family",
                },
            },
        ],
    }


def expected_product(
    product_id: str = PRODUCT_ID,
    *,
    name: str = "Oak Lounge Chair",
) -> dict[str, Any]:
    return {
        "id": product_id,
        "name": name,
        "description": "Solid oak frame with linen upholstery.",
        "price": "799.99",
        "discount_price": "749.5",
        "width": "80.5",
        "height": "90",
        "depth": "75",
        "weight": "12.25",
        "materials": ["oak", "linen"],
        "category": {"id": CATEGORY_ID, "name": "Chairs"},
        "seller": {"id": SELLER_ID, "business_name": "Artisan Furniture"},
        "colors": [
            {
                "id": COLOR_ONE_ID,
                "value": "Oak",
                "stock_quantity": 5,
                "display_order": 2,
            },
            {
                "id": COLOR_TWO_ID,
                "value": "Walnut",
                "stock_quantity": 3,
                "display_order": 2,
            },
        ],
        "images": [
            {
                "id": IMAGE_ONE_ID,
                "url": "https://images.example.com/one.jpg",
                "is_primary": True,
                "display_order": 2,
                "color_id": COLOR_ONE_ID,
            },
            {
                "id": IMAGE_THREE_ID,
                "url": "https://images.example.com/three.jpg",
                "is_primary": True,
                "display_order": 2,
                "color_id": COLOR_TWO_ID,
            },
            {
                "id": IMAGE_TWO_ID,
                "url": "https://images.example.com/two.jpg",
                "is_primary": False,
                "display_order": 0,
                "color_id": None,
            },
        ],
        "enrichment_attributes": [
            {"kind": "color_family", "value": "warm"},
            {"kind": "style", "value": "classic"},
            {"kind": "style", "value": "contemporary"},
        ],
    }


def assert_catalogue_request(request: httpx.Request) -> None:
    params = request.url.params
    assert request.method == "GET"
    assert request.url.path == "/rest/v1/product"
    assert request.headers["accept"] == "application/json"
    assert request.headers["apikey"] == TEST_PUBLISHABLE_KEY
    assert request.headers["authorization"] == f"Bearer {TEST_ACCESS_TOKEN}"
    assert params["select"] == CATALOG_SELECT
    assert "*" not in params["select"]
    assert params["lifecycle_state"] == "eq.published"
    assert params["seller.approval_state"] == "eq.approved"
    assert params["category.is_active"] == "eq.true"
    assert params["colors.stock_quantity"] == "gt.0"
    assert params["enrichment_assignments.confirmation_state"] == ("eq.party_confirmed")
    assert params["order"] == "id.asc"
    assert params["colors.order"] == "display_order.asc,id.asc"
    assert params["images.order"] == "is_primary.desc,display_order.asc,id.asc"


def unexpected_catalogue_call(_request: httpx.Request) -> httpx.Response:
    raise AssertionError("The catalogue upstream must not be called")


@pytest.mark.anyio
async def test_catalogue_requires_authentication() -> None:
    async with catalogue_client(unexpected_catalogue_call) as client:
        response = await client.get("/v1/catalog/products")

    assert response.status_code == 401
    assert response.json() == AUTHENTICATION_REQUIRED
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_catalogue_list_returns_only_safe_eligible_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert_catalogue_request(request)
        assert request.url.params["limit"] == "21"
        assert request.url.params["offset"] == "0"
        return httpx.Response(200, json=[product_payload()])

    async with catalogue_client(handler) as client:
        response = await client.get(
            "/v1/catalog/products",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "items": [expected_product()],
        "limit": 20,
        "offset": 0,
        "has_more": False,
    }
    assert "private AI suggestion" not in response.text
    assert "lifecycle_state" not in response.text
    assert "approval_state" not in response.text
    assert "is_active" not in response.text
    assert TEST_ACCESS_TOKEN not in response.text
    assert TEST_PUBLISHABLE_KEY not in response.text


@pytest.mark.anyio
async def test_catalogue_list_pagination_and_product_order_are_stable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert_catalogue_request(request)
        assert request.url.params["limit"] == "2"
        assert request.url.params["offset"] == "3"
        return httpx.Response(
            200,
            json=[
                product_payload(PRODUCT_ID, name="Second UUID"),
                product_payload(LOWER_PRODUCT_ID, name="First UUID"),
            ],
        )

    async with catalogue_client(handler) as client:
        response = await client.get(
            "/v1/catalog/products?limit=1&offset=3",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "items": [expected_product(LOWER_PRODUCT_ID, name="First UUID")],
        "limit": 1,
        "offset": 3,
        "has_more": True,
    }


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=51", "offset=-1"],
)
@pytest.mark.anyio
async def test_catalogue_rejects_invalid_pagination(query: str) -> None:
    async with catalogue_client(unexpected_catalogue_call) as client:
        response = await client.get(
            f"/v1/catalog/products?{query}",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "eligibility_rule",
    ["published_product", "approved_seller", "active_category", "in_stock_color"],
)
@pytest.mark.anyio
async def test_catalogue_defensively_removes_ineligible_products(
    eligibility_rule: str,
) -> None:
    payload = product_payload()
    if eligibility_rule == "published_product":
        payload["lifecycle_state"] = "draft"
    elif eligibility_rule == "approved_seller":
        payload["seller"]["approval_state"] = "pending"
    elif eligibility_rule == "active_category":
        payload["category"]["is_active"] = False
    else:
        for color in payload["colors"]:
            color["stock_quantity"] = 0

    def handler(request: httpx.Request) -> httpx.Response:
        assert_catalogue_request(request)
        return httpx.Response(200, json=[payload])

    async with catalogue_client(handler) as client:
        response = await client.get(
            "/v1/catalog/products",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["has_more"] is False


@pytest.mark.anyio
async def test_catalogue_empty_product_list_is_stable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert_catalogue_request(request)
        return httpx.Response(200, json=[])

    async with catalogue_client(handler) as client:
        response = await client.get(
            "/v1/catalog/products?limit=5&offset=10",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "limit": 5,
        "offset": 10,
        "has_more": False,
    }


@pytest.mark.anyio
async def test_catalogue_product_detail_returns_verified_product() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert_catalogue_request(request)
        assert request.url.params["id"] == f"eq.{PRODUCT_ID}"
        assert request.url.params["limit"] == "1"
        return httpx.Response(200, json=[product_payload()])

    async with catalogue_client(handler) as client:
        response = await client.get(
            f"/v1/catalog/products/{PRODUCT_ID}",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 200
    assert response.json() == expected_product()


@pytest.mark.anyio
async def test_catalogue_product_detail_returns_safe_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert_catalogue_request(request)
        return httpx.Response(200, json=[])

    async with catalogue_client(handler) as client:
        response = await client.get(
            f"/v1/catalog/products/{PRODUCT_ID}",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 404
    assert response.json() == PRODUCT_NOT_FOUND


@pytest.mark.anyio
async def test_catalogue_product_detail_hides_ineligible_product() -> None:
    payload = product_payload()
    payload["category"]["is_active"] = False

    def handler(request: httpx.Request) -> httpx.Response:
        assert_catalogue_request(request)
        return httpx.Response(200, json=[payload])

    async with catalogue_client(handler) as client:
        response = await client.get(
            f"/v1/catalog/products/{PRODUCT_ID}",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 404
    assert response.json() == PRODUCT_NOT_FOUND


@pytest.mark.anyio
async def test_catalogue_timeout_returns_safe_503() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private upstream timeout", request=request)

    async with catalogue_client(handler) as client:
        response = await client.get(
            "/v1/catalog/products",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 503
    assert response.json() == CATALOGUE_SERVICE_UNAVAILABLE
    assert TEST_ACCESS_TOKEN not in response.text


@pytest.mark.anyio
async def test_catalogue_network_failure_returns_safe_503() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private network diagnostic", request=request)

    async with catalogue_client(handler) as client:
        response = await client.get(
            "/v1/catalog/products",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 503
    assert response.json() == CATALOGUE_SERVICE_UNAVAILABLE
    assert TEST_ACCESS_TOKEN not in response.text


@pytest.mark.anyio
async def test_catalogue_5xx_returns_safe_503() -> None:
    raw_upstream_error = "private database diagnostic"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=raw_upstream_error)

    async with catalogue_client(handler) as client:
        response = await client.get(
            "/v1/catalog/products",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 503
    assert response.json() == CATALOGUE_SERVICE_UNAVAILABLE
    assert raw_upstream_error not in response.text
    assert TEST_ACCESS_TOKEN not in response.text
    assert TEST_PUBLISHABLE_KEY not in response.text


@pytest.mark.anyio
async def test_catalogue_4xx_returns_safe_502() -> None:
    raw_upstream_error = "private PostgREST relationship error"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": raw_upstream_error})

    async with catalogue_client(handler) as client:
        response = await client.get(
            "/v1/catalog/products",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 502
    assert response.json() == CATALOGUE_UPSTREAM_ERROR
    assert raw_upstream_error not in response.text
    assert TEST_ACCESS_TOKEN not in response.text
    assert TEST_PUBLISHABLE_KEY not in response.text


@pytest.mark.anyio
async def test_catalogue_malformed_json_returns_safe_502() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not valid JSON")

    async with catalogue_client(handler) as client:
        response = await client.get(
            "/v1/catalog/products",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 502
    assert response.json() == CATALOGUE_UPSTREAM_ERROR


@pytest.mark.parametrize("malformed_field", ["id", "price"])
@pytest.mark.anyio
async def test_catalogue_malformed_data_returns_safe_502(
    malformed_field: str,
) -> None:
    payload = deepcopy(product_payload())
    payload[malformed_field] = "not-valid"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[payload])

    async with catalogue_client(handler) as client:
        response = await client.get(
            "/v1/catalog/products",
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 502
    assert response.json() == CATALOGUE_UPSTREAM_ERROR
    assert "not-valid" not in response.text
