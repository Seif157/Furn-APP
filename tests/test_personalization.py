"""Phase 9B and section 6.10: tie-breaking on history, and labelled seller offers.

The two promises under test: personalization may reorder matches and may never
change which products match, and a seller's made-to-order offer never appears
next to real results or without a label.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr, TypeAdapter

from app.auth.dependencies import get_auth_gateway
from app.auth.models import AuthenticatedRequestContext
from app.catalog.dependencies import (
    get_catalogue_gateway,
    get_offering_gateway,
    get_purchase_history_gateway,
)
from app.catalog.gateway import SupabaseCatalogueGateway
from app.catalog.normalization import NormalizedProduct, normalize_product
from app.catalog.upstream_models import UpstreamProduct
from app.core.cache import AICaches
from app.main import app
from app.personalization.gateway import (
    PurchasedLine,
    SupabasePurchaseHistoryGateway,
    parse_history_rows,
)
from app.personalization.profile import MIN_PURCHASES, TasteProfile, build_profile
from app.personalization.service import taste_profile
from app.recommendations.offerings import (
    SellerOffering,
    SupabaseOfferingGateway,
    parse_offering_rows,
)
from app.search import ranking
from app.search.dependencies import get_optional_ai_provider
from app.search.models import SoftPreferences, build_specification
from app.search.service import search_products
from tests.test_catalog import TEST_ACCESS_TOKEN, TEST_USER_ID, build_test_settings
from tests.test_search_endpoint import StubProvider, VerifiedAuthGateway, seed_response


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def context() -> AuthenticatedRequestContext:
    return AuthenticatedRequestContext(
        user_id=TEST_USER_ID, access_token=SecretStr(TEST_ACCESS_TOKEN)
    )


def catalogue() -> tuple[NormalizedProduct, ...]:
    products = TypeAdapter(tuple[UpstreamProduct, ...]).validate_json(
        seed_catalogue_json()
    )
    return tuple(normalize_product(product) for product in products)


def seed_catalogue_json() -> str:
    from tests import seed_catalogue as seed

    return seed.as_json_fixture()


# --- reading a history ------------------------------------------------------


def test_only_real_bought_lines_survive() -> None:
    product_id = uuid4()
    rows = [
        {"product_id": str(product_id), "unit_price": "1200.00"},
        {"product_id": None, "unit_price": "10"},
        {"product_id": str(uuid4()), "unit_price": "not a price"},
        {"product_id": str(uuid4()), "unit_price": "-5"},
        "junk",
    ]

    assert parse_history_rows(rows) == (
        PurchasedLine(product_id=product_id, unit_price=Decimal("1200.00")),
    )


@pytest.mark.anyio
async def test_the_history_read_is_scoped_to_the_verified_user() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabasePurchaseHistoryGateway(
            client=client, settings=build_test_settings()
        )
        await gateway.recent_lines(authenticated_request=context())

    params = seen[0].url.params
    assert params["purchase_order.customer_profile.user_id"] == f"eq.{TEST_USER_ID}"
    assert seen[0].headers["authorization"] == f"Bearer {TEST_ACCESS_TOKEN}"


@pytest.mark.anyio
async def test_an_unreadable_history_is_no_history() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabasePurchaseHistoryGateway(
            client=client, settings=build_test_settings()
        )

        assert await gateway.recent_lines(authenticated_request=context()) == ()


# --- the profile ------------------------------------------------------------


def test_one_purchase_is_not_a_taste() -> None:
    profile = build_profile(catalogue()[:1], prices_paid=(Decimal("5000"),))

    assert profile.is_useful is False


def test_a_profile_summarises_what_was_actually_bought() -> None:
    bought = catalogue()[:3]

    profile = build_profile(
        bought, prices_paid=(Decimal("1000"), Decimal("3000"), Decimal("2000"))
    )

    assert profile.is_useful is True
    assert profile.purchases == 3
    assert profile.typical_price == Decimal("2000")
    assert profile.categories <= {p.category.slug for p in bought if p.category.slug}
    assert profile.bought_product_ids == {p.id for p in bought}


def test_the_price_that_counts_is_the_one_they_paid() -> None:
    """Not today's price: a discount they never saw says nothing about them."""

    bought = catalogue()[:2]

    profile = build_profile(bought, prices_paid=(Decimal("100"), Decimal("300")))

    assert profile.typical_price == Decimal("200")


# --- what it may change -----------------------------------------------------


def test_a_profile_can_never_change_which_products_match() -> None:
    products = catalogue()
    specification = build_specification(category="sofa", query="a sofa").specification
    profile = build_profile(
        products[:3], prices_paid=(Decimal("1000"), Decimal("1200"))
    )

    plain = search_products(products, specification)
    personalized = search_products(products, specification, profile)

    assert plain.match_count == personalized.match_count
    assert {item.product_id for item in plain.items} == {
        item.product_id for item in personalized.items
    }


def test_taste_weighs_less_than_anything_the_customer_said() -> None:
    assert ranking.WEIGHTS["taste"] < min(
        weight for name, weight in ranking.WEIGHTS.items() if name != "taste"
    )


def test_a_product_unlike_the_history_still_scores_on_its_merits() -> None:
    products = catalogue()
    profile = TasteProfile(
        colours=frozenset({"navy"}),
        materials=frozenset({"marble"}),
        purchases=MIN_PURCHASES,
    )
    soft = SoftPreferences(colours=("beige",))

    parts = {
        part.component: part.value
        for part in ranking.score_parts(products[0], soft, None, profile)
    }

    assert "taste" in parts
    # The stated preference is still scored, independently of the history.
    assert "colours" in parts


def test_no_profile_means_no_taste_component() -> None:
    products = catalogue()

    parts = ranking.score_parts(products[0], SoftPreferences(), None, None)

    assert all(part.component != "taste" for part in parts)


# --- the service ------------------------------------------------------------


class StubHistory:
    def __init__(self, lines: tuple[PurchasedLine, ...]) -> None:
        self.lines = lines
        self.calls = 0

    async def recent_lines(self, **kwargs: Any) -> tuple[PurchasedLine, ...]:
        self.calls += 1
        return self.lines


class StubCatalogue:
    def __init__(self, products: tuple[UpstreamProduct, ...]) -> None:
        self.products = products
        self.requested: list[tuple[UUID, ...]] = []

    async def list_products(self, **kwargs: Any) -> tuple[UpstreamProduct, ...]:
        return self.products

    async def get_product(self, **kwargs: Any) -> UpstreamProduct | None:
        return None

    async def list_by_ids(
        self, *, authenticated_request: Any, product_ids: tuple[UUID, ...]
    ) -> tuple[UpstreamProduct, ...]:
        self.requested.append(product_ids)
        return tuple(p for p in self.products if p.id in set(product_ids))


def upstream() -> tuple[UpstreamProduct, ...]:
    return TypeAdapter(tuple[UpstreamProduct, ...]).validate_json(seed_catalogue_json())


@pytest.mark.anyio
async def test_no_history_means_no_profile_and_no_product_lookup() -> None:
    history = StubHistory(())
    products = StubCatalogue(upstream())

    profile = await taste_profile(
        authenticated_request=context(), history=history, catalogue=products
    )

    assert profile is None
    assert products.requested == []


@pytest.mark.anyio
async def test_a_profile_is_built_once_and_cached_per_user() -> None:
    bought = upstream()[:2]
    history = StubHistory(
        tuple(
            PurchasedLine(product_id=product.id, unit_price=Decimal("1000"))
            for product in bought
        )
    )
    products = StubCatalogue(upstream())
    caches = AICaches(ttl_seconds=600)

    first = await taste_profile(
        authenticated_request=context(),
        history=history,
        catalogue=products,
        caches=caches,
    )
    second = await taste_profile(
        authenticated_request=context(),
        history=history,
        catalogue=products,
        caches=caches,
    )

    assert first is not None and first == second
    assert history.calls == 1
    assert len(products.requested) == 1


# --- seller offers ----------------------------------------------------------


def test_an_offering_needs_a_title_a_seller_and_a_sane_price() -> None:
    identifier, seller = uuid4(), uuid4()
    rows = [
        {
            "id": str(identifier),
            "title": " Custom wardrobe ",
            "description": "  ",
            "published_price": "12000",
            "marketplace_party_id": str(seller),
        },
        {"id": str(uuid4()), "title": "", "marketplace_party_id": str(seller)},
        {"id": str(uuid4()), "title": "No seller"},
        {
            "id": str(uuid4()),
            "title": "Negative",
            "published_price": "-1",
            "marketplace_party_id": str(seller),
        },
    ]

    assert parse_offering_rows(rows) == (
        SellerOffering(
            id=identifier,
            title="Custom wardrobe",
            description=None,
            price=Decimal("12000"),
            seller_id=seller,
        ),
    )


@pytest.mark.anyio
async def test_only_published_offerings_are_asked_for() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseOfferingGateway(client=client, settings=build_test_settings())
        await gateway.published(authenticated_request=context())

    assert seen[0].url.params["publication_state"] == "eq.published"


# --- through the endpoint ---------------------------------------------------


@asynccontextmanager
async def search_client(
    provider: StubProvider,
    *,
    lines: tuple[PurchasedLine, ...] = (),
    offers: tuple[SellerOffering, ...] = (),
) -> AsyncIterator[httpx.AsyncClient]:
    class StubOfferings:
        def __init__(self) -> None:
            self.calls = 0

        async def published(self, **kwargs: Any) -> tuple[SellerOffering, ...]:
            self.calls += 1
            return offers

    offerings = StubOfferings()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(seed_response)
    ) as upstream_client:
        catalogue_gateway = SupabaseCatalogueGateway(
            client=upstream_client, settings=build_test_settings()
        )
        app.dependency_overrides[get_auth_gateway] = VerifiedAuthGateway
        app.dependency_overrides[get_catalogue_gateway] = lambda: catalogue_gateway
        app.dependency_overrides[get_optional_ai_provider] = lambda: provider
        app.dependency_overrides[get_purchase_history_gateway] = lambda: StubHistory(
            lines
        )
        app.dependency_overrides[get_offering_gateway] = lambda: offerings
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                client.offerings = offerings  # type: ignore[attr-defined]
                yield client
        finally:
            for dependency in (
                get_auth_gateway,
                get_catalogue_gateway,
                get_optional_ai_provider,
                get_purchase_history_gateway,
                get_offering_gateway,
            ):
                app.dependency_overrides.pop(dependency, None)


@pytest.mark.anyio
async def test_a_search_says_when_history_moved_the_order() -> None:
    bought = upstream()[:2]
    lines = tuple(
        PurchasedLine(product_id=product.id, unit_price=Decimal("9000"))
        for product in bought
    )
    provider = StubProvider({"category": "sofa"})

    async with search_client(provider, lines=lines) as client:
        response = await client.post(
            "/v1/search",
            json={"query": "a sofa"},
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    body = response.json()
    assert response.status_code == 200
    assert isinstance(body["personalized"], bool)
    assert body["match_count"] > 0


@pytest.mark.anyio
async def test_a_customer_with_no_history_gets_the_unpersonalized_answer() -> None:
    provider = StubProvider({"category": "sofa"})

    async with search_client(provider) as client:
        response = await client.post(
            "/v1/search",
            json={"query": "a sofa"},
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    body = response.json()
    assert body["personalized"] is False
    assert body["seller_offers"] == []


@pytest.mark.anyio
async def test_seller_offers_appear_only_when_nothing_matched() -> None:
    offer = SellerOffering(
        id=uuid4(),
        title="Custom wardrobe, any size",
        description="Made to measure",
        price=Decimal("18000"),
        seller_id=uuid4(),
    )
    impossible = StubProvider({"category": "sofa", "max_price": 1})

    async with search_client(impossible, offers=(offer,)) as client:
        empty = await client.post(
            "/v1/search",
            json={"query": "عايز كنبة بجنيه"},
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    body = empty.json()
    assert body["match_count"] == 0
    assert len(body["seller_offers"]) == 1
    shown = body["seller_offers"][0]
    assert shown["title"] == "Custom wardrobe, any size"
    assert shown["price"] == "18000"
    # Labelled, in the customer's language, and never called a product.
    assert "الكتالوج" in shown["label"]
    assert body["items"] == []


@pytest.mark.anyio
async def test_a_successful_search_never_shows_a_seller_offer() -> None:
    offer = SellerOffering(
        id=uuid4(), title="Custom sofa", description=None, price=None, seller_id=uuid4()
    )
    provider = StubProvider({"category": "sofa"})

    async with search_client(provider, offers=(offer,)) as client:
        response = await client.post(
            "/v1/search",
            json={"query": "a sofa"},
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )
        calls = client.offerings.calls  # type: ignore[attr-defined]

    assert response.json()["match_count"] > 0
    assert response.json()["seller_offers"] == []
    # Not even asked for: an advertisement is not a fallback when there is an
    # answer.
    assert calls == 0
