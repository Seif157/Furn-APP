"""Intake: a described problem becomes a real service, a job becomes a form."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.auth.dependencies import get_auth_gateway
from app.auth.models import AuthenticatedRequestContext
from app.core.cache import AICaches
from app.intake.brief import BriefDraft, brief_from_draft
from app.intake.dependencies import get_service_directory_gateway
from app.intake.gateway import (
    ServiceType,
    SupabaseServiceDirectoryGateway,
    parse_service_rows,
)
from app.intake.triage import (
    MIN_CONFIDENCE,
    TriageDraft,
    services_from_draft,
    triage_prompt,
)
from app.main import app
from app.search.dependencies import get_optional_ai_provider
from tests.test_catalog import TEST_ACCESS_TOKEN, TEST_USER_ID, build_test_settings
from tests.test_search_endpoint import StubProvider, VerifiedAuthGateway

ASSEMBLY = ServiceType(id=uuid4(), name="Assembly", description="Put it together")
REPAIR = ServiceType(id=uuid4(), name="Repair", description="Fix what broke")
DELIVERY = ServiceType(id=uuid4(), name="Delivery", description=None)
SERVICES = (ASSEMBLY, REPAIR, DELIVERY)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def context() -> AuthenticatedRequestContext:
    return AuthenticatedRequestContext(
        user_id=TEST_USER_ID, access_token=SecretStr(TEST_ACCESS_TOKEN)
    )


# --- reading the real directory ---------------------------------------------


def test_a_service_needs_an_id_and_a_name_this_build_can_show() -> None:
    identifier = uuid4()
    rows = [
        {"id": str(identifier), "name": "Assembly", "is_active": True},
        {"id": str(uuid4()), "is_active": True},  # nothing to call it
        {"id": "not-a-uuid", "name": "Repair", "is_active": True},
        {"id": str(uuid4()), "name": "Hidden", "is_active": False},
        "junk",
    ]

    parsed = parse_service_rows(rows)

    assert parsed == (ServiceType(id=identifier, name="Assembly"),)


def test_a_differently_named_column_is_still_a_name() -> None:
    identifier = uuid4()

    parsed = parse_service_rows(
        [{"id": str(identifier), "title": "Upholstery", "details": "Re-cover it"}]
    )

    assert parsed == (
        ServiceType(id=identifier, name="Upholstery", description="Re-cover it"),
    )


@pytest.mark.anyio
async def test_the_directory_is_read_with_the_callers_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json=[{"id": str(ASSEMBLY.id), "name": "Assembly", "is_active": True}]
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseServiceDirectoryGateway(
            client=client, settings=build_test_settings()
        )
        services = await gateway.list_active(authenticated_request=context())

    assert [service.name for service in services] == ["Assembly"]
    assert seen[0].headers["authorization"] == f"Bearer {TEST_ACCESS_TOKEN}"
    assert seen[0].url.params["is_active"] == "eq.true"


@pytest.mark.anyio
async def test_an_unreadable_directory_is_empty_not_an_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseServiceDirectoryGateway(
            client=client, settings=build_test_settings()
        )

        assert await gateway.list_active(authenticated_request=context()) == ()


# --- what the model may choose ----------------------------------------------


def test_the_draft_carries_positions_not_services() -> None:
    """An invented service has nowhere to live: there is no id field."""

    assert set(TriageDraft.model_fields) == {"choices", "clarification_question"}
    assert set(TriageDraft().model_fields_set) == set()


def test_a_number_outside_the_list_points_at_nothing() -> None:
    draft = TriageDraft.model_validate(
        {
            "choices": [
                {"number": 0, "confidence": 0.9},
                {"number": 99, "confidence": 0.9},
                {"number": -1, "confidence": 0.9},
            ]
        }
    )

    assert services_from_draft(draft, SERVICES) == ()


def test_the_same_service_twice_is_one_answer() -> None:
    draft = TriageDraft.model_validate(
        {
            "choices": [
                {"number": 2, "confidence": 0.9},
                {"number": 2, "confidence": 0.5},
            ]
        }
    )

    matched = services_from_draft(draft, SERVICES)

    assert [match.service.id for match in matched] == [REPAIR.id]
    assert matched[0].confidence == Decimal("0.90")


def test_a_hunch_too_weak_to_act_on_is_dropped() -> None:
    weak = float(MIN_CONFIDENCE - Decimal("0.01"))
    draft = TriageDraft.model_validate({"choices": [{"number": 1, "confidence": weak}]})

    assert services_from_draft(draft, SERVICES) == ()


def test_the_prompt_carries_the_real_services_and_the_customers_words() -> None:
    prompt = triage_prompt(SERVICES, "باب الدولاب اتكسر")

    assert "1. Assembly - Put it together" in prompt
    assert "3. Delivery" in prompt
    assert prompt.endswith("باب الدولاب اتكسر")


# --- the furnishing brief ---------------------------------------------------


def test_a_flat_becomes_rooms_the_form_can_store() -> None:
    draft = BriefDraft.model_validate(
        {
            "rooms": [
                {"room": "غرفة نوم", "quantity": 3},
                {"room": "ريسبشن", "quantity": 1},
            ],
            "total_budget": 150000,
            "styles": ["مودرن"],
            "feels": ["fancy"],
        }
    )

    brief = brief_from_draft(draft)

    assert [(room.room_type, room.quantity) for room in brief.rooms] == [
        ("bedroom", 3),
        ("reception", 1),
    ]
    assert brief.total_budget == Decimal("150000")
    assert brief.styles == ("modern",)
    # "fancy" is not a vocabulary feel: reported, never mapped to "luxury".
    assert brief.feels == ()
    assert [term.surface for term in brief.unresolved] == ["fancy"]


def test_a_room_nobody_recognises_is_reported_not_guessed() -> None:
    draft = BriefDraft.model_validate({"rooms": [{"room": "wine cellar"}]})

    brief = brief_from_draft(draft)

    assert brief.rooms == ()
    assert brief.unresolved[0].field == "room_type"
    assert brief.unresolved[0].surface == "wine cellar"


@pytest.mark.parametrize("quantity", [0, -3, 99])
def test_an_impossible_count_falls_back_to_one_room(quantity: int) -> None:
    draft = BriefDraft.model_validate(
        {"rooms": [{"room": "bedroom", "quantity": quantity}]}
    )

    brief = brief_from_draft(draft)

    assert [(room.room_type, room.quantity) for room in brief.rooms] == [("bedroom", 1)]


@pytest.mark.parametrize("budget", [0, -1, 10**12])
def test_an_impossible_budget_is_dropped(budget: int) -> None:
    draft = BriefDraft.model_validate({"total_budget": budget})

    assert brief_from_draft(draft).total_budget is None


# --- the endpoints ----------------------------------------------------------


@asynccontextmanager
async def intake_client(
    provider: StubProvider, services: tuple[ServiceType, ...] = SERVICES
) -> AsyncIterator[httpx.AsyncClient]:
    class StubDirectory:
        async def list_active(
            self, *, authenticated_request: AuthenticatedRequestContext
        ) -> tuple[ServiceType, ...]:
            return services

    app.dependency_overrides[get_auth_gateway] = VerifiedAuthGateway
    app.dependency_overrides[get_optional_ai_provider] = lambda: provider
    app.dependency_overrides[get_service_directory_gateway] = StubDirectory
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client
    finally:
        for dependency in (
            get_auth_gateway,
            get_optional_ai_provider,
            get_service_directory_gateway,
        ):
            app.dependency_overrides.pop(dependency, None)


async def post(
    client: httpx.AsyncClient,
    path: str,
    body: Mapping[str, Any],
    *,
    authenticated: bool = True,
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"} if authenticated else {}
    return await client.post(path, json=dict(body), headers=headers)


@pytest.mark.anyio
async def test_a_described_problem_returns_real_services() -> None:
    provider = StubProvider({"choices": [{"number": 2, "confidence": 0.85}]})

    async with intake_client(provider) as client:
        response = await post(
            client, "/v1/intake/service", {"description": "باب الدولاب اتكسر"}
        )

    body = response.json()
    assert response.status_code == 200
    assert body["language"] == "ar"
    assert body["services"] == [
        {
            "id": str(REPAIR.id),
            "name": "Repair",
            "description": "Fix what broke",
            "confidence": "0.85",
        }
    ]
    # The real service list travelled in the prompt, not the instruction.
    assert "Repair - Fix what broke" in provider.calls[0]


@pytest.mark.anyio
async def test_a_problem_the_marketplace_does_not_serve_returns_nothing() -> None:
    provider = StubProvider(
        {"choices": [], "clarification_question": "تقصد تركيب ولا تصليح؟"}
    )

    async with intake_client(provider) as client:
        response = await post(
            client, "/v1/intake/service", {"description": "عايز حد يرسم لوحة"}
        )

    body = response.json()
    assert response.status_code == 200
    assert body["services"] == []
    assert body["clarification"] == "تقصد تركيب ولا تصليح؟"


@pytest.mark.anyio
async def test_no_directory_means_no_guess() -> None:
    provider = StubProvider({"choices": [{"number": 1, "confidence": 0.9}]})

    async with intake_client(provider, services=()) as client:
        response = await post(
            client, "/v1/intake/service", {"description": "my table wobbles"}
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "service_directory_unavailable"
    # Nothing was asked of the model: there was nothing to choose from.
    assert provider.calls == []


@pytest.mark.anyio
async def test_intake_requires_authentication() -> None:
    provider = StubProvider({"choices": []})

    async with intake_client(provider) as client:
        for path in ("/v1/intake/service", "/v1/intake/furnishing"):
            response = await post(
                client, path, {"description": "anything"}, authenticated=False
            )
            assert response.status_code == 401

    assert provider.calls == []


@pytest.mark.anyio
async def test_a_furnishing_job_comes_back_as_a_form() -> None:
    provider = StubProvider(
        {
            "rooms": [{"room": "غرفة نوم", "quantity": 2}, {"room": "ريسبشن"}],
            "total_budget": 150000,
            "styles": ["مودرن"],
        }
    )

    async with intake_client(provider) as client:
        response = await post(
            client,
            "/v1/intake/furnishing",
            {"description": "عايز أفرش شقة أوضتين نوم وريسبشن بـ ١٥٠ ألف"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["language"] == "ar"
    assert body["rooms"] == [
        {"room_type": {"slug": "bedroom", "label": "غرفة نوم"}, "quantity": 2},
        {"room_type": {"slug": "reception", "label": "ريسبشن"}, "quantity": 1},
    ]
    assert body["total_budget"] == "150000"
    assert body["styles"] == [{"slug": "modern", "label": "مودرن"}]


@pytest.mark.anyio
async def test_the_same_description_is_not_asked_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = StubProvider({"rooms": [{"room": "bedroom"}]})
    monkeypatch.setattr(
        app.state, "ai_caches", AICaches(ttl_seconds=600), raising=False
    )

    async with intake_client(provider) as client:
        first = await post(
            client, "/v1/intake/furnishing", {"description": "furnish my bedroom"}
        )
        second = await post(
            client, "/v1/intake/furnishing", {"description": "furnish my bedroom"}
        )

    assert first.json() == second.json()
    assert len(provider.calls) == 1


@pytest.mark.anyio
async def test_an_untrustworthy_answer_is_refused() -> None:
    provider = StubProvider({"rooms": "bedroom"})

    async with intake_client(provider) as client:
        response = await post(
            client, "/v1/intake/furnishing", {"description": "furnish my flat"}
        )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "search_upstream_error"


@pytest.mark.anyio
async def test_the_service_id_is_never_taken_from_the_model() -> None:
    """Even an answer that names an id returns only the row the backend sent."""

    invented = uuid4()
    provider = StubProvider(
        {
            "choices": [{"number": 1, "confidence": 0.9, "id": str(invented)}],
            "services": [{"id": str(invented), "name": "Free repairs"}],
        }
    )

    async with intake_client(provider) as client:
        response = await post(
            client, "/v1/intake/service", {"description": "assemble my wardrobe"}
        )

    body = response.json()
    assert [service["id"] for service in body["services"]] == [str(ASSEMBLY.id)]
    assert str(invented) not in response.text
    assert UUID(body["services"][0]["id"]) == ASSEMBLY.id
