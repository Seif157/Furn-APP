"""Inferred style, room and feel tags: the fuzzy half of search.

Nothing here is a seller's word. These tests exist to keep two promises that
are easy to break later: a guess may order results but never filter them, and
a customer is always told which statements are guesses.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr, TypeAdapter

from app.auth.dependencies import get_auth_gateway
from app.auth.models import AuthenticatedRequestContext
from app.catalog.dependencies import get_catalogue_gateway, get_search_tag_gateway
from app.catalog.gateway import SupabaseCatalogueGateway
from app.catalog.normalization import (
    FEELS,
    ROOM_TYPES,
    STYLES,
    InferredTag,
    NormalizedProduct,
    normalize_product,
    with_tags,
)
from app.catalog.tags import (
    SupabaseSearchTagGateway,
    attach_inferred_tags,
    parse_tag_rows,
    wants_inferred_tags,
)
from app.catalog.upstream_models import UpstreamProduct
from app.main import app
from app.recommendations.explanations import preference_reasons
from app.search import ranking
from app.search.dependencies import get_optional_ai_provider
from app.search.models import SoftPreferences, build_specification
from app.search.service import search_products
from tests import seed_catalogue as seed
from tests.test_catalog import TEST_ACCESS_TOKEN, TEST_USER_ID, build_test_settings
from tests.test_search_endpoint import StubProvider, VerifiedAuthGateway, seed_response

MockHandler = Callable[[httpx.Request], httpx.Response]
PRODUCT_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def context() -> AuthenticatedRequestContext:
    return AuthenticatedRequestContext(
        user_id=TEST_USER_ID,
        access_token=SecretStr(TEST_ACCESS_TOKEN),
    )


def normalized_seed() -> tuple[NormalizedProduct, ...]:
    products = TypeAdapter(tuple[UpstreamProduct, ...]).validate_json(
        seed.as_json_fixture()
    )
    return tuple(normalize_product(product) for product in products)


# --- the vocabularies -------------------------------------------------------


def test_both_languages_reach_the_same_slug() -> None:
    # This is the whole reason styles stopped being free text: a tag written
    # "modern" could never match a customer who typed "مودرن".
    assert STYLES.lookup("مودرن") is STYLES.lookup("Modern")
    assert ROOM_TYPES.lookup("ريسبشن") is ROOM_TYPES.lookup("reception")
    assert FEELS.lookup("كوزي") is FEELS.lookup("cozy")
    assert ROOM_TYPES.lookup("انتريه").slug == "reception"


def test_an_unknown_word_is_reported_not_guessed() -> None:
    build = build_specification(styles=("brutalist",), feels=("expensive",), query="x")
    assert build.specification.soft.styles == ()
    assert build.specification.soft.feels == ()
    assert {term.field for term in build.unresolved} == {"styles", "feels"}
    assert {term.surface for term in build.unresolved} == {"brutalist", "expensive"}


# --- reading the tag table --------------------------------------------------


def test_a_row_the_vocabulary_does_not_know_is_dropped() -> None:
    rows = [
        {
            "product_id": str(PRODUCT_ID),
            "tag_kind": "style",
            "tag_slug": "modern",
            "confidence": "0.8",
        },
        {
            "product_id": str(PRODUCT_ID),
            "tag_kind": "style",
            "tag_slug": "brutalist",
            "confidence": "0.9",
        },
        {
            "product_id": str(PRODUCT_ID),
            "tag_kind": "vibe",
            "tag_slug": "modern",
            "confidence": "0.9",
        },
        {
            "product_id": str(PRODUCT_ID),
            "tag_kind": "feel",
            "tag_slug": "cosy",
            "confidence": "1.4",
        },
        {
            "product_id": "not-a-uuid",
            "tag_kind": "feel",
            "tag_slug": "cosy",
            "confidence": "0.5",
        },
        "junk",
    ]

    assert parse_tag_rows(rows) == {
        PRODUCT_ID: (
            InferredTag(kind="style", slug="modern", confidence=Decimal("0.8")),
        )
    }


@pytest.mark.anyio
async def test_the_gateway_sends_the_callers_token_and_only_the_asked_ids() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "product_id": str(PRODUCT_ID),
                    "tag_kind": "feel",
                    "tag_slug": "cosy",
                    "confidence": 0.6,
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseSearchTagGateway(
            client=client, settings=build_test_settings()
        )
        tags = await gateway.tags_for(
            authenticated_request=context(), product_ids=(PRODUCT_ID,)
        )

    assert tags[PRODUCT_ID][0].slug == "cosy"
    assert seen[0].headers["authorization"] == f"Bearer {TEST_ACCESS_TOKEN}"
    assert seen[0].url.params["product_id"] == f"in.({PRODUCT_ID})"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(404, json={}),
        lambda request: httpx.Response(500, json={}),
        lambda request: httpx.Response(200, content=b"not json"),
    ],
)
async def test_a_missing_tag_table_costs_ranking_not_the_search(
    handler: MockHandler,
) -> None:
    """404 is the answer before the migration is applied. It must be silent."""

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseSearchTagGateway(
            client=client, settings=build_test_settings()
        )
        result = await gateway.tags_for(
            authenticated_request=context(), product_ids=(PRODUCT_ID,)
        )

    assert result == {}


@pytest.mark.anyio
async def test_a_timeout_is_silent_too() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseSearchTagGateway(
            client=client, settings=build_test_settings()
        )
        result = await gateway.tags_for(
            authenticated_request=context(), product_ids=(PRODUCT_ID,)
        )

    assert result == {}


# --- when tags are fetched at all -------------------------------------------


def test_a_sentence_without_a_style_room_or_feel_wants_no_tags() -> None:
    plain = build_specification(category="sofa", query="a sofa").specification
    fuzzy = build_specification(
        category="sofa", feels=("cosy",), query="x"
    ).specification

    assert wants_inferred_tags(plain) is False
    assert wants_inferred_tags(fuzzy) is True


@pytest.mark.anyio
async def test_no_request_is_made_for_a_plain_sentence() -> None:
    class ExplodingGateway:
        async def tags_for(self, **kwargs: Any) -> dict[UUID, tuple[InferredTag, ...]]:
            raise AssertionError("no tag request should be made")

    products = normalized_seed()[:2]
    unchanged = await attach_inferred_tags(
        products,
        gateway=ExplodingGateway(),
        authenticated_request=context(),
        specification=build_specification(
            category="sofa", query="a sofa"
        ).specification,
    )

    assert unchanged == products


# --- ranking ----------------------------------------------------------------


def test_a_guess_never_scores_as_high_as_a_stated_fact() -> None:
    product = normalized_seed()[0]
    guessed = with_tags(
        product, (InferredTag(kind="style", slug="modern", confidence=Decimal("1")),)
    )

    (part,) = ranking.score_parts(guessed, SoftPreferences(styles=("modern",)), None)

    assert part.value == ranking.INFERRED_CEILING < Decimal("1")


def test_confidence_orders_two_guesses() -> None:
    product = normalized_seed()[0]
    soft = SoftPreferences(feels=("cosy",))
    sure = with_tags(
        product, (InferredTag(kind="feel", slug="cosy", confidence=Decimal("0.7")),)
    )
    shaky = with_tags(
        product, (InferredTag(kind="feel", slug="cosy", confidence=Decimal("0.3")),)
    )

    assert ranking.score_parts(sure, soft, None)[0].value == Decimal("0.7")
    assert ranking.score_parts(shaky, soft, None)[0].value == Decimal("0.3")
    assert ranking.score_parts(product, soft, None)[0].value == Decimal("0")


def test_a_tag_can_never_exclude_a_product() -> None:
    """Feels and styles are soft. Only hard constraints decide what matches."""

    products = normalized_seed()
    specification = build_specification(
        category="sofa", feels=("hotel_like",), styles=("art_deco",), query="x"
    ).specification
    tagged = tuple(
        with_tags(
            product,
            (InferredTag(kind="feel", slug="hotel_like", confidence=Decimal("0.9")),),
        )
        for product in products
    )

    without = search_products(products, specification)
    with_guesses = search_products(tagged, specification)

    assert without.match_count == with_guesses.match_count
    assert {item.product_id for item in without.items} == {
        item.product_id for item in with_guesses.items
    }


# --- what the customer is told ----------------------------------------------


def test_a_guess_is_worded_as_a_guess_in_both_languages() -> None:
    product = with_tags(
        normalized_seed()[0],
        (
            InferredTag(kind="style", slug="modern", confidence=Decimal("0.9")),
            InferredTag(kind="feel", slug="cosy", confidence=Decimal("0.5")),
        ),
    )
    soft = SoftPreferences(styles=("modern",), feels=("cosy",))

    english = preference_reasons(product, soft, "en")
    assert [reason.text for reason in english] == [
        "looks modern (our guess)",
        "feels cosy (our guess)",
    ]
    assert {reason.basis for reason in english} == {"inferred"}

    arabic = preference_reasons(product, soft, "ar")
    assert all(reason.basis == "inferred" for reason in arabic)
    assert "تقديرنا" in arabic[0].text


def test_nothing_is_claimed_about_a_product_that_carries_no_tag() -> None:
    product = normalized_seed()[0]

    assert preference_reasons(product, SoftPreferences(feels=("luxury",)), "en") == ()


# --- end to end -------------------------------------------------------------


@asynccontextmanager
async def tagged_search_client(
    tags: dict[UUID, tuple[InferredTag, ...]],
    provider: StubProvider,
    record: list[tuple[UUID, ...]],
) -> AsyncIterator[httpx.AsyncClient]:
    class RecordingTagGateway:
        async def tags_for(
            self,
            *,
            authenticated_request: AuthenticatedRequestContext,
            product_ids: tuple[UUID, ...],
        ) -> dict[UUID, tuple[InferredTag, ...]]:
            record.append(product_ids)
            return tags

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(seed_response)
    ) as upstream:
        catalogue_gateway = SupabaseCatalogueGateway(
            client=upstream, settings=build_test_settings()
        )
        app.dependency_overrides[get_auth_gateway] = VerifiedAuthGateway
        app.dependency_overrides[get_catalogue_gateway] = lambda: catalogue_gateway
        app.dependency_overrides[get_optional_ai_provider] = lambda: provider
        app.dependency_overrides[get_search_tag_gateway] = RecordingTagGateway
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                yield client
        finally:
            for dependency in (
                get_auth_gateway,
                get_catalogue_gateway,
                get_optional_ai_provider,
                get_search_tag_gateway,
            ):
                app.dependency_overrides.pop(dependency, None)


@pytest.mark.anyio
async def test_a_fuzzy_sentence_ranks_by_tags_and_says_they_are_guesses() -> None:
    provider = StubProvider(
        {"category": "sofa", "styles": ["modern"], "feels": ["cosy"]}
    )
    record: list[tuple[UUID, ...]] = []
    # Tag one real seed sofa, so any ranking difference is attributable.
    favourite = next(p for p in normalized_seed() if p.category.slug == "sofas")
    tags = {
        favourite.id: (
            InferredTag(kind="style", slug="modern", confidence=Decimal("0.8")),
            InferredTag(kind="feel", slug="cosy", confidence=Decimal("0.8")),
        )
    }

    async with tagged_search_client(tags, provider, record) as client:
        response = await client.post(
            "/v1/search",
            json={"query": "كنبة مودرن دافئة ومريحة"},
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert record and favourite.id in record[0]
    assert body["interpretation"]["feels"] == [{"slug": "cosy", "label": "دافئ ومريح"}]
    top = body["items"][0]
    assert top["product"]["id"] == str(favourite.id)
    guesses = [reason for reason in top["reasons"] if reason["basis"] == "inferred"]
    assert len(guesses) == 2
    assert all("تقديرنا" in reason["text"] for reason in guesses)
    assert all(
        reason["basis"] == "catalogue"
        for reason in top["reasons"]
        if reason not in guesses
    )


@pytest.mark.anyio
async def test_search_still_answers_when_the_tag_table_is_missing() -> None:
    provider = StubProvider({"category": "sofa", "feels": ["cosy"]})
    record: list[tuple[UUID, ...]] = []

    async with tagged_search_client({}, provider, record) as client:
        response = await client.post(
            "/v1/search",
            json={"query": "a cosy sofa"},
            headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["match_count"] > 0
    assert all(
        reason["basis"] == "catalogue"
        for item in body["items"]
        for reason in item["reasons"]
    )
