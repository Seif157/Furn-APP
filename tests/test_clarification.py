"""Phase 7A: the follow-up question, and when it is worth asking."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter

from app.catalog.normalization import NormalizedProduct, normalize_product
from app.catalog.upstream_models import UpstreamProduct
from app.search.clarification import MIN_BROAD_MATCHES, follow_up
from app.search.models import (
    Language,
    PriceRange,
    build_specification,
    states_a_requirement,
)
from tests import seed_catalogue as seed
from tests.test_catalog import TEST_ACCESS_TOKEN
from tests.test_inferred_tags import tagged_search_client
from tests.test_search_endpoint import StubProvider


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def catalogue() -> tuple[NormalizedProduct, ...]:
    products = TypeAdapter(tuple[UpstreamProduct, ...]).validate_json(
        seed.as_json_fixture()
    )
    return tuple(normalize_product(product) for product in products)


def ask(
    *,
    matches: tuple[NormalizedProduct, ...],
    match_count: int | None = None,
    clarification: str | None = None,
    language: Language = "en",
    **specification: Any,
) -> Any:
    return follow_up(
        specification=build_specification(query="x", **specification).specification,
        matches=matches,
        match_count=len(matches) if match_count is None else match_count,
        clarification=clarification,
        language=language,
    )


# --- when nothing is asked --------------------------------------------------


def test_a_detailed_sentence_is_answered_not_interrogated() -> None:
    """Section 6.3: a detailed query searches immediately."""

    assert (
        ask(
            matches=catalogue(),
            category="sofa",
            price=PriceRange(maximum=Decimal("30000")),
        )
        is None
    )


def test_a_short_list_needs_no_question() -> None:
    products = catalogue()[:3]

    assert ask(matches=products, match_count=3) is None


def test_nothing_is_asked_when_nothing_matched() -> None:
    assert ask(matches=(), match_count=0, clarification="What kind?") is None


# --- the category question --------------------------------------------------


def test_a_categoryless_broad_search_offers_the_categories_that_matched() -> None:
    products = catalogue()

    asked = ask(matches=products, match_count=len(products))

    assert asked is not None
    assert asked.field == "category"
    offered = {option.value for option in asked.options}
    present = {p.category.slug for p in products if p.category.slug}
    assert offered <= present
    assert len(offered) >= 2


def test_a_vague_sentence_keeps_the_parsers_own_question() -> None:
    products = catalogue()

    asked = ask(
        matches=products,
        match_count=len(products),
        clarification="بتدور على أثاث لأوضة إيه؟",
        language="ar",
    )

    assert asked is not None
    assert asked.question == "بتدور على أثاث لأوضة إيه؟"
    # The options are still the backend's, built from real matches.
    assert all(option.send == option.label for option in asked.options)


def test_the_options_speak_the_customers_language() -> None:
    products = catalogue()

    english = ask(matches=products, match_count=len(products), language="en")
    arabic = ask(matches=products, match_count=len(products), language="ar")

    assert english is not None and arabic is not None
    assert english.question == "What are you looking for?"
    assert arabic.question == "بتدور على إيه؟"
    assert {o.value for o in english.options} == {o.value for o in arabic.options}
    assert {o.label for o in english.options} != {o.label for o in arabic.options}


# --- the budget question ----------------------------------------------------


def test_a_category_without_a_budget_offers_real_price_bands() -> None:
    sofas = tuple(p for p in catalogue() if p.category.slug == "sofas")
    assert len(sofas) >= MIN_BROAD_MATCHES

    asked = ask(matches=sofas, match_count=len(sofas), category="sofa")

    assert asked is not None
    assert asked.field == "price"
    assert len(asked.options) == 3
    low_band, middle_band, high_band = asked.options
    assert low_band.value.startswith("max:")
    assert high_band.value.startswith("min:")
    # The bands meet, and both boundaries sit inside what actually matched.
    low = Decimal(low_band.value.removeprefix("max:"))
    high = Decimal(high_band.value.removeprefix("min:"))
    assert middle_band.value == f"{low}:{high}"
    prices = sorted(product.effective_price for product in sofas)
    assert prices[0] < low < high < prices[-1]


def test_no_bands_when_everything_costs_about_the_same() -> None:
    products = catalogue()
    similar = tuple(
        product.model_copy(update={"effective_price": Decimal("10000")})
        for product in products[:MIN_BROAD_MATCHES]
    )

    assert ask(matches=similar, match_count=len(similar), category="sofa") is None


# --- through the endpoint ---------------------------------------------------


@pytest.mark.anyio
async def test_the_endpoint_returns_a_tappable_question() -> None:
    # A sentence with no category at all: "I need furniture".
    provider = StubProvider({"clarification_question": "What kind of furniture?"})
    record: list[Any] = []

    async with tagged_search_client({}, provider, record) as client:
        response = await client.post(
            "/v1/search",
            json={"query": "I need furniture"},
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["clarification"] == "What kind of furniture?"
    asked = body["follow_up"]
    assert asked["field"] == "category"
    assert asked["question"] == "What kind of furniture?"
    assert len(asked["options"]) >= 2
    for option in asked["options"]:
        assert option["send"] and option["label"] and option["value"]


# --- a sentence that asked for nothing -------------------------------------


def test_what_counts_as_asking_for_something() -> None:
    def asks(**kwargs: Any) -> bool:
        return states_a_requirement(
            build_specification(query="x", **kwargs).specification
        )

    assert asks(category="sofa") is True
    assert asks(preferred_colours=("beige",)) is True
    assert asks(feels=("cosy",)) is True
    assert asks(price=PriceRange(maximum=Decimal("30000"))) is True
    # Nothing but the raw sentence: as a search this means "everything".
    assert asks() is False
    # The default says nothing; choosing the other way is a statement.
    assert asks(in_stock_only=True) is False
    assert asks(in_stock_only=False) is True


@pytest.mark.anyio
async def test_an_off_topic_question_is_not_answered_with_the_catalogue() -> None:
    """Measured live: "ما هي عاصمة فرنسا؟" parses to no constraints at all and
    used to return 43 of 44 products under a question asking what they want."""

    provider = StubProvider({"clarification_question": "بتدور على إيه؟"})
    record: list[Any] = []

    async with tagged_search_client({}, provider, record) as client:
        response = await client.post(
            "/v1/search",
            json={"query": "ما هي عاصمة فرنسا؟"},
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["awaiting_answer"] is True
    assert body["items"] == []
    assert body["match_count"] == 0
    assert body["personalized"] is False
    # Not "nothing found": a question, with answers drawn from real products.
    assert body["clarification"] == "بتدور على إيه؟"
    assert len(body["follow_up"]["options"]) >= 2
    # The catalogue was still examined, and the response says so honestly.
    assert body["candidate_count"] > 0


@pytest.mark.anyio
async def test_a_real_search_is_never_withheld() -> None:
    provider = StubProvider({"category": "sofa"})
    record: list[Any] = []

    async with tagged_search_client({}, provider, record) as client:
        response = await client.post(
            "/v1/search",
            json={"query": "a sofa"},
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    body = response.json()
    assert body["awaiting_answer"] is False
    assert body["items"]
    assert body["match_count"] > 0


def test_nothing_is_withheld_when_there_is_no_question_to_ask() -> None:
    """An empty screen with nothing on it is worse than a list nobody asked for.

    With too few matches to offer categories and no question from the parser,
    the products are shown rather than withheld.
    """

    from app.search.responses import build_search_response
    from app.search.service import search_products

    products = catalogue()[:3]
    specification = build_specification(query="anything at all").specification
    results = search_products(products, specification)
    upstream = TypeAdapter(tuple[UpstreamProduct, ...]).validate_json(
        seed.as_json_fixture()
    )

    response = build_search_response(
        upstream[:3],
        normalized=products,
        results=results,
        specification=specification,
        query="anything at all",
        language="en",
        clarification=None,
        unresolved=(),
        truncated=False,
        states_requirement=False,
    )

    assert response.follow_up is None
    assert response.awaiting_answer is False
    assert response.items


@pytest.mark.anyio
async def test_tapping_an_option_searches_for_it() -> None:
    """The tapped text is an ordinary query with the first message as history."""

    provider = StubProvider({"category": "sofa"})
    record: list[Any] = []

    async with tagged_search_client({}, provider, record) as client:
        response = await client.post(
            "/v1/search",
            json={"query": "Sofas", "history": ["I need furniture"]},
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["interpretation"]["category"]["slug"] == "sofas"
    assert body["match_count"] > 0
    assert provider.calls == ["I need furniture ... Sofas"]


@pytest.mark.anyio
async def test_an_answered_search_asks_nothing_further() -> None:
    provider = StubProvider({"category": "sofa", "max_price": 30000})
    record: list[Any] = []

    async with tagged_search_client({}, provider, record) as client:
        response = await client.post(
            "/v1/search",
            json={"query": "a sofa under 30000"},
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 200
    assert response.json()["follow_up"] is None
