"""Tests for the authenticated natural-language search endpoint (Phase 5C).

The AI provider is always a stub and the catalogue is always a mock transport
serving the Phase 5 seed, so the suite contacts neither Google nor Supabase.
The gateway, the normalizer, the parser guardrails, the ranking, and the
response transform are all the real ones.
"""

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.ai.provider import AIProviderUnavailableError, AIResponseInvalidError
from app.auth.dependencies import get_auth_gateway
from app.auth.gateway import AuthenticationGateway
from app.auth.models import AuthenticatedUser
from app.catalog.dependencies import get_catalogue_gateway
from app.catalog.gateway import CatalogueGateway, SupabaseCatalogueGateway
from app.main import app
from app.search.dependencies import get_optional_ai_provider
from tests import seed_catalogue as seed
from tests.test_catalog import TEST_ACCESS_TOKEN, TEST_USER_ID, build_test_settings

MockHandler = Callable[[httpx.Request], httpx.Response]

AUTHENTICATION_REQUIRED = {
    "detail": {
        "code": "authentication_required",
        "message": "Authentication is required.",
    }
}
SEARCH_UNAVAILABLE = {
    "detail": {
        "code": "search_unavailable",
        "message": "Search is temporarily unavailable.",
    }
}
SEARCH_UPSTREAM_ERROR = {
    "detail": {
        "code": "search_upstream_error",
        "message": "The search request could not be understood.",
    }
}
CATALOGUE_SERVICE_UNAVAILABLE = {
    "detail": {
        "code": "catalogue_service_unavailable",
        "message": "The catalogue is temporarily unavailable.",
    }
}

# The same sentence tests/test_seed_catalogue.py runs as a hand-built
# specification, so the endpoint's answer can be compared to a known one.
SOFA_DRAFT: dict[str, Any] = {
    "category": "sofa",
    "max_price": 15000,
    "max_width_cm": 220,
    "preferred_colours": ["beige"],
    "styles": ["modern"],
}


class VerifiedAuthGateway:
    async def authenticate(self, access_token: str) -> AuthenticatedUser:
        assert access_token == TEST_ACCESS_TOKEN
        return AuthenticatedUser(user_id=TEST_USER_ID)


class StubProvider:
    def __init__(self, answer: Mapping[str, Any] | Exception) -> None:
        self._answer = answer
        self.calls: list[str] = []

    async def generate_json(
        self, *, instruction: str, prompt: str, schema: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.calls.append(prompt)
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def seed_response(request: httpx.Request) -> httpx.Response:
    """Serve the whole seed catalogue as PostgREST would."""

    return httpx.Response(200, content=seed.as_json_fixture().encode("utf-8"))


def unavailable_catalogue(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, json={})


def unexpected_catalogue_call(request: httpx.Request) -> httpx.Response:
    raise AssertionError("The catalogue must not be called")


@asynccontextmanager
async def search_client(
    handler: MockHandler,
    provider: StubProvider | None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Wire the real gateway and parser to stubs at the two network edges."""

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as upstream_client:
        catalogue_gateway = SupabaseCatalogueGateway(
            client=upstream_client, settings=build_test_settings()
        )

        async def override_auth_gateway() -> AuthenticationGateway:
            return VerifiedAuthGateway()

        async def override_catalogue_gateway() -> CatalogueGateway:
            return catalogue_gateway

        app.dependency_overrides[get_auth_gateway] = override_auth_gateway
        app.dependency_overrides[get_catalogue_gateway] = override_catalogue_gateway
        if provider is not None:

            async def override_provider() -> StubProvider:
                return provider

            app.dependency_overrides[get_optional_ai_provider] = override_provider
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                yield client
        finally:
            app.dependency_overrides.pop(get_auth_gateway, None)
            app.dependency_overrides.pop(get_catalogue_gateway, None)
            app.dependency_overrides.pop(get_optional_ai_provider, None)


async def post_search(
    client: httpx.AsyncClient, body: dict[str, Any], *, authenticated: bool = True
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"} if authenticated else {}
    return await client.post("/v1/search", json=body, headers=headers)


# --- authorization ----------------------------------------------------------


@pytest.mark.anyio
async def test_search_requires_authentication_before_spending_a_call() -> None:
    provider = StubProvider(SOFA_DRAFT)

    async with search_client(unexpected_catalogue_call, provider) as client:
        response = await post_search(client, {"query": "a sofa"}, authenticated=False)

    assert response.status_code == 401
    assert response.json() == AUTHENTICATION_REQUIRED
    assert response.headers["www-authenticate"] == "Bearer"
    # Identity is established before the model is asked anything.
    assert provider.calls == []


# --- the happy path ---------------------------------------------------------


@pytest.mark.anyio
async def test_a_sentence_returns_the_same_products_a_hand_built_spec_finds() -> None:
    provider = StubProvider(SOFA_DRAFT)

    async with search_client(seed_response, provider) as client:
        response = await post_search(
            client,
            {
                "query": "modern beige sofa under 15,000 and no wider than 220 cm",
                "limit": 10,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    # tests/test_seed_catalogue.py reaches these same numbers deterministically.
    assert payload["candidate_count"] == 41
    assert payload["match_count"] == 5
    assert payload["truncated"] is False
    assert payload["limit"] == 10
    assert len(payload["items"]) == 5
    assert payload["items"][0]["product"]["id"].endswith("000000000017")
    assert payload["clarification"] is None
    assert payload["unresolved"] == []
    # Ranking order is what matters, and it holds. The absolute scores sit
    # below the hand-built run's because this sentence also states a style,
    # and no seed product carries confirmed style enrichment, so that
    # component scores zero for every candidate and drags the weighted mean
    # down uniformly. Uniformly is the important word: order is unchanged.
    scores = [Decimal(item["score"]) for item in payload["items"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.anyio
async def test_the_response_says_what_the_backend_understood() -> None:
    provider = StubProvider(SOFA_DRAFT)

    async with search_client(seed_response, provider) as client:
        response = await post_search(client, {"query": "a modern beige sofa"})

    interpretation = response.json()["interpretation"]
    assert interpretation["category"] == {"slug": "sofas", "label": "Sofas"}
    assert interpretation["price"] == {"minimum": None, "maximum": "15000"}
    assert interpretation["width_cm"] == {"minimum": None, "maximum": "220"}
    assert interpretation["in_stock_only"] is True
    assert interpretation["preferred_colours"] == [{"slug": "beige", "label": "beige"}]
    assert interpretation["styles"] == ["modern"]


@pytest.mark.anyio
async def test_every_item_reports_the_constraints_it_satisfied() -> None:
    provider = StubProvider(SOFA_DRAFT)

    async with search_client(seed_response, provider) as client:
        response = await post_search(client, {"query": "a modern beige sofa"})

    for item in response.json()["items"]:
        assert "category" in item["matched"]
        assert "price" in item["matched"]
        assert "width" in item["matched"]


@pytest.mark.anyio
async def test_an_arabic_sentence_searches_the_same_catalogue() -> None:
    provider = StubProvider(
        {"category": "كنب", "max_price": 15000, "preferred_colours": ["بيج"]}
    )

    async with search_client(seed_response, provider) as client:
        response = await post_search(
            client, {"query": "عايز كنبة مودرن بيج أقل من ١٥ ألف"}
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["interpretation"]["category"]["slug"] == "sofas"
    assert payload["interpretation"]["preferred_colours"][0]["slug"] == "beige"
    assert payload["match_count"] > 0


@pytest.mark.anyio
async def test_a_vague_sentence_returns_a_question_and_the_whole_catalogue() -> None:
    provider = StubProvider({"clarification_question": "Which room is it for?"})

    async with search_client(seed_response, provider) as client:
        response = await post_search(client, {"query": "I need furniture"})

    payload = response.json()
    assert payload["clarification"] == "Which room is it for?"
    # No hard constraint was stated, so nothing is excluded.
    assert payload["match_count"] == 41


@pytest.mark.anyio
async def test_an_unrecognised_word_is_reported_rather_than_guessed() -> None:
    provider = StubProvider({"category": "coffee table"})

    async with search_client(seed_response, provider) as client:
        response = await post_search(client, {"query": "I need a coffee table"})

    payload = response.json()
    assert payload["unresolved"] == [{"field": "category", "surface": "coffee table"}]
    assert payload["interpretation"]["category"] is None


# --- what must never reach a client -----------------------------------------


@pytest.mark.anyio
async def test_search_leaks_no_credential_and_no_private_catalogue_field() -> None:
    provider = StubProvider(SOFA_DRAFT)

    async with search_client(seed_response, provider) as client:
        response = await post_search(client, {"query": "a modern beige sofa"})

    assert TEST_ACCESS_TOKEN not in response.text
    for private_field in (
        "lifecycle_state",
        "approval_state",
        "is_active",
        "confirmation_state",
    ):
        assert private_field not in response.text


@pytest.mark.anyio
async def test_draft_and_hidden_products_never_appear_in_results() -> None:
    provider = StubProvider({"in_stock_only": False})

    async with search_client(seed_response, provider) as client:
        response = await post_search(client, {"query": "show me everything"})

    payload = response.json()
    # The seed holds 44 rows. Product 041 is draft, 042 is hidden, and 043 has
    # no stock in any colour, so 41 remain. Asking for out-of-stock products
    # relaxes only the stock preference; it can never relax publication state.
    assert payload["candidate_count"] == 41
    assert payload["match_count"] == 41
    returned = {item["product"]["id"] for item in payload["items"]}
    for excluded in ("041", "042", "043"):
        assert not any(product_id.endswith(excluded) for product_id in returned)
    assert "draft" not in response.text
    assert "hidden" not in response.text


# --- failure behaviour ------------------------------------------------------


@pytest.mark.anyio
async def test_an_unconfigured_provider_refuses_without_touching_the_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Nothing overrides the provider dependency, and the lifespan never ran, so
    # this exercises the real "no GEMINI_API_KEY" path.
    monkeypatch.delattr(app.state, "ai_provider", raising=False)

    async with search_client(unexpected_catalogue_call, None) as client:
        response = await post_search(client, {"query": "a sofa"})

    assert response.status_code == 503
    assert response.json() == SEARCH_UNAVAILABLE


@pytest.mark.anyio
async def test_a_provider_that_cannot_answer_is_a_retryable_503() -> None:
    provider = StubProvider(AIProviderUnavailableError())

    async with search_client(unexpected_catalogue_call, provider) as client:
        response = await post_search(client, {"query": "a sofa"})

    assert response.status_code == 503
    assert response.json() == SEARCH_UNAVAILABLE


@pytest.mark.anyio
async def test_an_untrustworthy_answer_is_a_502() -> None:
    provider = StubProvider(AIResponseInvalidError())

    async with search_client(unexpected_catalogue_call, provider) as client:
        response = await post_search(client, {"query": "a sofa"})

    assert response.status_code == 502
    assert response.json() == SEARCH_UPSTREAM_ERROR


@pytest.mark.anyio
async def test_a_draft_with_an_impossible_budget_is_a_502() -> None:
    provider = StubProvider({"category": "sofa", "max_price": -1})

    async with search_client(unexpected_catalogue_call, provider) as client:
        response = await post_search(client, {"query": "a free sofa"})

    assert response.status_code == 502
    assert response.json() == SEARCH_UPSTREAM_ERROR


@pytest.mark.anyio
async def test_an_unavailable_catalogue_is_reported_as_such() -> None:
    provider = StubProvider(SOFA_DRAFT)

    async with search_client(unavailable_catalogue, provider) as client:
        response = await post_search(client, {"query": "a sofa"})

    assert response.status_code == 503
    assert response.json() == CATALOGUE_SERVICE_UNAVAILABLE


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body",
    [
        {"query": ""},
        {"query": "x" * 501},
        {"query": "a sofa", "limit": 0},
        {"query": "a sofa", "limit": 51},
        {"query": "a sofa", "extra": "forbidden"},
        {},
    ],
)
async def test_unusable_requests_are_rejected_before_a_call_is_spent(
    body: dict[str, Any],
) -> None:
    provider = StubProvider(SOFA_DRAFT)

    async with search_client(unexpected_catalogue_call, provider) as client:
        response = await post_search(client, body)

    assert response.status_code == 422
    assert provider.calls == []


@pytest.mark.anyio
async def test_a_catalogue_larger_than_one_search_is_reported_as_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A silently shortened candidate set would produce confidently wrong
    # results, so the response says so instead.
    monkeypatch.setattr("app.search.router.CANDIDATE_LIMIT", 5)
    provider = StubProvider({"in_stock_only": False})

    async with search_client(seed_response, provider) as client:
        response = await post_search(client, {"query": "anything"})

    payload = response.json()
    assert payload["truncated"] is True
    assert payload["candidate_count"] <= 5


@pytest.mark.anyio
async def test_a_search_that_matches_nothing_says_why() -> None:
    # Observed live: "give me a free sofa for 1 pound" parses into a real
    # constraint and correctly matches nothing. An empty list with no reason
    # is a dead end, so the response reports which constraint did the work.
    provider = StubProvider({"category": "sofa", "max_price": 1})

    async with search_client(seed_response, provider) as client:
        response = await post_search(client, {"query": "a sofa for 1 pound"})

    payload = response.json()
    assert payload["match_count"] == 0
    assert payload["items"] == []
    exclusions = {row["constraint"]: row["excluded"] for row in payload["excluded_by"]}
    # Counts overlap: a product can fail several constraints and is counted
    # under each. Every one of the 41 is over a one-pound budget, and 33 are
    # also the wrong category.
    assert exclusions["price"] == 41
    assert exclusions["category"] == 33
    # Largest count first, so a client can name the constraint to relax first.
    assert payload["excluded_by"][0]["constraint"] == "price"


@pytest.mark.anyio
async def test_nothing_is_excluded_when_nothing_was_constrained() -> None:
    provider = StubProvider({"clarification_question": "Which room?"})

    async with search_client(seed_response, provider) as client:
        response = await post_search(client, {"query": "I need furniture"})

    assert response.json()["excluded_by"] == []


# --- answering in the customer's language -----------------------------------


@pytest.mark.anyio
async def test_an_arabic_sentence_is_answered_with_arabic_labels() -> None:
    provider = StubProvider(
        {
            "category": "كنب",
            "required_materials": ["خشب زان"],
            "preferred_colours": ["بيج"],
            "max_price": 15000,
        }
    )

    async with search_client(seed_response, provider) as client:
        response = await post_search(client, {"query": "عايز كنبة بيج خشب زان"})

    payload = response.json()
    assert payload["language"] == "ar"
    interpretation = payload["interpretation"]
    assert interpretation["category"] == {"slug": "sofas", "label": "كنب"}
    assert interpretation["materials"][0] == {
        "slug": "beech_wood",
        "label": "خشب زان",
    }
    assert interpretation["preferred_colours"][0]["label"] == "بيج"


@pytest.mark.anyio
async def test_the_same_search_in_english_keeps_the_same_slugs() -> None:
    arabic = StubProvider({"category": "كنب", "preferred_colours": ["بيج"]})
    english = StubProvider({"category": "Sofas", "preferred_colours": ["beige"]})

    async with search_client(seed_response, arabic) as client:
        arabic_payload = (await post_search(client, {"query": "عايز كنبة بيج"})).json()
    async with search_client(seed_response, english) as client:
        english_payload = (
            await post_search(client, {"query": "I want a beige sofa"})
        ).json()

    # Labels differ, slugs do not, so a client can branch on one and show the
    # other. The products returned are identical.
    assert arabic_payload["language"] == "ar"
    assert english_payload["language"] == "en"
    assert arabic_payload["interpretation"]["category"]["label"] == "كنب"
    assert english_payload["interpretation"]["category"]["label"] == "Sofas"
    assert (
        arabic_payload["interpretation"]["category"]["slug"]
        == english_payload["interpretation"]["category"]["slug"]
    )
    assert [item["product"]["id"] for item in arabic_payload["items"]] == [
        item["product"]["id"] for item in english_payload["items"]
    ]


@pytest.mark.anyio
async def test_a_mixed_sentence_is_answered_in_arabic() -> None:
    # An Egyptian customer reaching for an English product word is an Arabic
    # speaker, not an English one.
    provider = StubProvider({"category": "Sofas"})

    async with search_client(seed_response, provider) as client:
        response = await post_search(client, {"query": "عايز modern sofa"})

    payload = response.json()
    assert payload["language"] == "ar"
    assert payload["interpretation"]["category"]["label"] == "كنب"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("query", "expected_language", "expected_message"),
    [
        ("عايز كنبة", "ar", "البحث غير متاح مؤقتًا. برجاء المحاولة بعد قليل."),
        ("I need a sofa", "en", "Search is temporarily unavailable."),
    ],
)
async def test_errors_are_reported_in_the_customers_language(
    query: str, expected_language: str, expected_message: str
) -> None:
    provider = StubProvider(AIProviderUnavailableError())

    async with search_client(unexpected_catalogue_call, provider) as client:
        response = await post_search(client, {"query": query})

    assert response.status_code == 503
    detail = response.json()["detail"]
    # The code never changes with language, so a client branches on it and
    # shows the message.
    assert detail["code"] == "search_unavailable"
    assert detail["message"] == expected_message


@pytest.mark.anyio
async def test_an_untrustworthy_answer_is_explained_in_arabic() -> None:
    provider = StubProvider(AIResponseInvalidError())

    async with search_client(unexpected_catalogue_call, provider) as client:
        response = await post_search(client, {"query": "عايز كنبة"})

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "search_upstream_error"
    assert detail["message"] == "تعذّر فهم طلب البحث. برجاء إعادة صياغته."


@pytest.mark.anyio
async def test_product_text_is_never_translated() -> None:
    # Catalogue text is a marketplace fact and is shown as the seller wrote it.
    provider = StubProvider({"category": "Sofas"})

    async with search_client(seed_response, provider) as client:
        response = await post_search(client, {"query": "I want a sofa"})

    payload = response.json()
    assert payload["language"] == "en"
    # Seed product names are Arabic; an English response keeps them Arabic.
    assert any("كنبة" in item["product"]["name"] for item in payload["items"])
