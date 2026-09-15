"""Deterministic safety tests for the Phase 3.2C live acceptance utility."""

import inspect
import json
from io import StringIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from scripts import live_phase_3_2c_acceptance as acceptance
from scripts import live_rls_acceptance as base

TEST_PUBLISHABLE_KEY = "sb_publishable_phase32c_sentinel"
TEST_ACCESS_TOKEN = "<access-token-sentinel>"
TEST_REFRESH_TOKEN = "<refresh-token-sentinel>"
TEST_PASSWORD = "<password-sentinel>"


def _test_identifier(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"phase-3.2c:{label}"))


CUSTOMER_ID = _test_identifier("customer")
SELLER_ID = _test_identifier("seller")
PRODUCT_ID = _test_identifier("product")
SERVICE_ID = _test_identifier("service")
ADDRESS_ID = _test_identifier("address")
PRODUCT_REVIEW_ID = _test_identifier("product-review")
PARTY_REVIEW_ID = _test_identifier("party-review")
REQUEST_IDS = {
    state: _test_identifier(f"furnishing-{state}")
    for state in ("draft", "open", "accepted", "withdrawn", "closed")
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class TTYStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def build_settings() -> Settings:
    return Settings(
        SUPABASE_URL="://".join(("https", "testing.invalid")),
        SUPABASE_PUBLISHABLE_KEY=TEST_PUBLISHABLE_KEY,
        SUPABASE_AUTH_TIMEOUT_SECONDS=5.0,
        _env_file=None,
    )


def build_session(token: str = TEST_ACCESS_TOKEN) -> base.PasswordSession:
    return base.PasswordSession(
        access_token=SecretStr(token),
        refresh_token=SecretStr(TEST_REFRESH_TOKEN),
    )


def furnishing_row(state: str) -> dict[str, object]:
    return {
        "id": REQUEST_IDS[state],
        "customer_profile_id": CUSTOMER_ID,
        "address_id": ADDRESS_ID,
        "title": "test-title",
        "requirements_description": "test-requirements",
        "reference_image_urls": [],
        "budget_min": None,
        "budget_max": None,
        "requested_timing": None,
        "offer_deadline": None,
        "lifecycle_state": state,
        "created_at": "2026-01-01T00:00:00Z",
        "coarse_location": None,
    }


def snapshot(state: str) -> base.RecordSnapshot:
    row = furnishing_row(state)
    return base.RecordSnapshot(
        relation="furnishing_request",
        fields=acceptance.FURNISHING_REQUEST_FIELDS,
        identifier=SecretStr(REQUEST_IDS[state]),
        values=row,
    )


def test_reuses_exact_interactive_branch_and_credential_safety(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(base.sys, "stdin", TTYStringIO())
    monkeypatch.setattr(base.sys, "stderr", TTYStringIO())
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: base.TEST_BRANCH_CONFIRMATION,
    )
    passwords = iter((TEST_PASSWORD, f"seller-{TEST_PASSWORD}"))
    monkeypatch.setattr(base.getpass, "getpass", lambda _prompt: next(passwords))

    secrets = base.collect_interactive_secrets()

    assert base.TEST_BRANCH_CONFIRMATION == "FAKE-DATA TESTING BRANCH"
    assert secrets.model_dump() == {}
    output = capsys.readouterr().out
    assert TEST_PASSWORD not in repr(secrets)
    assert TEST_PASSWORD not in output


def test_refuses_noninteractive_and_inexact_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(base.sys, "stdin", StringIO())
    monkeypatch.setattr(base.sys, "stderr", StringIO())
    with pytest.raises(base.AcceptanceFailure) as noninteractive:
        base.collect_interactive_secrets()
    assert noninteractive.value.classification == "secure_terminal_required"

    monkeypatch.setattr(base.sys, "stdin", TTYStringIO())
    monkeypatch.setattr(base.sys, "stderr", TTYStringIO())
    monkeypatch.setattr("builtins.input", lambda _prompt: "testing")
    with pytest.raises(base.AcceptanceFailure) as unconfirmed:
        base.collect_interactive_secrets()
    assert unconfirmed.value.classification == "testing_branch_not_confirmed"


@pytest.mark.parametrize("name", sorted(base.FORBIDDEN_SECRET_ENVIRONMENT_NAMES))
def test_refuses_every_service_secret_configuration(name: str) -> None:
    with pytest.raises(base.AcceptanceFailure) as error:
        base.reject_forbidden_secret_configuration({name: "not-read"})
    assert error.value.classification == "forbidden_secret_configuration"


@pytest.mark.anyio
async def test_password_auth_uses_publishable_key_and_redacts_session() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/auth/v1/token"
        assert request.headers["apikey"] == TEST_PUBLISHABLE_KEY
        assert json.loads(request.content) == {
            "email": base.CUSTOMER_EMAIL,
            "password": TEST_PASSWORD,
        }
        return httpx.Response(
            200,
            json={
                "access_token": TEST_ACCESS_TOKEN,
                "refresh_token": TEST_REFRESH_TOKEN,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        session = await base.sign_in(
            client=client,
            settings=build_settings(),
            actor="customer",
            email=base.CUSTOMER_EMAIL,
            password=SecretStr(TEST_PASSWORD),
        )
    assert session.model_dump() == {}
    assert TEST_ACCESS_TOKEN not in repr(session)


@pytest.mark.anyio
async def test_anonymous_review_boundary_cross_checks_both_safe_target_kinds() -> None:
    review_rows = [
        {
            "id": PRODUCT_REVIEW_ID,
            "target_kind": "product",
            "target_product_id": PRODUCT_ID,
            "target_marketplace_party_id": None,
            "rating": 5,
            "comment": None,
            "created_at": "2026-01-01T00:00:00Z",
        },
        {
            "id": PARTY_REVIEW_ID,
            "target_kind": "marketplace_party",
            "target_product_id": None,
            "target_marketplace_party_id": SELLER_ID,
            "rating": 4,
            "comment": None,
            "created_at": "2026-01-01T00:00:00Z",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if "/rpc/" in request.url.path:
            return httpx.Response(403, json={"message": "private"})
        relation = request.url.path.rsplit("/", 1)[-1]
        if relation == "review":
            if request.url.params.get("select") in {
                "customer_profile_id",
                "target_service_request_id",
            }:
                return httpx.Response(403, json={"message": "private"})
            if request.url.params.get("target_kind") == "eq.service_request":
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=review_rows)
        if relation == "product":
            assert request.url.params["lifecycle_state"] == "eq.published"
            return httpx.Response(200, json=[{"id": PRODUCT_ID}])
        if relation == "marketplace_party":
            assert request.url.params["approval_state"] == "eq.approved"
            return httpx.Response(200, json=[{"id": SELLER_ID}])
        raise AssertionError("unexpected relation")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        await acceptance.verify_anonymous_review_boundary(api)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mode",
    ["helper_success", "sensitive_column_success", "service_leak"],
)
async def test_review_boundary_fails_closed_on_exposure(mode: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/rpc/" in request.url.path:
            return httpx.Response(
                200 if mode == "helper_success" else 403,
                json=None,
            )
        relation = request.url.path.rsplit("/", 1)[-1]
        if relation == "review":
            selected = request.url.params.get("select")
            if selected in {
                "customer_profile_id",
                "target_service_request_id",
            }:
                return httpx.Response(
                    200 if mode == "sensitive_column_success" else 403,
                    json=[],
                )
            if mode == "service_leak":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": PRODUCT_REVIEW_ID,
                            "target_kind": "service_request",
                            "target_product_id": None,
                            "target_marketplace_party_id": None,
                            "rating": 5,
                            "comment": None,
                            "created_at": "2026-01-01T00:00:00Z",
                        }
                    ],
                )
            return httpx.Response(200, json=[])
        raise AssertionError("unexpected relation")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        with pytest.raises(base.AcceptanceFailure) as error:
            await acceptance.verify_anonymous_review_boundary(api)
    expected = {
        "helper_success": "restricted_helper_executable",
        "sensitive_column_success": "private_column_exposed",
        "service_leak": "service_review_exposed",
    }[mode]
    assert error.value.classification == expected


@pytest.mark.anyio
async def test_customer_raw_review_is_scoped_to_helper_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/rpc/" in request.url.path:
            return httpx.Response(200, json=CUSTOMER_ID)
        assert request.url.params["customer_profile_id"] == f"eq.{CUSTOMER_ID}"
        return httpx.Response(
            200,
            json=[
                {
                    "id": PRODUCT_REVIEW_ID,
                    "customer_profile_id": CUSTOMER_ID,
                    "target_kind": "service_request",
                    "target_product_id": None,
                    "target_marketplace_party_id": None,
                    "target_service_request_id": SERVICE_ID,
                    "rating": 5,
                    "comment": "kept-in-memory",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        profile_id = await acceptance.verify_authenticated_review_owner(
            api,
            customer_session=build_session(),
        )
    assert profile_id.get_secret_value() == CUSTOMER_ID


@pytest.mark.anyio
async def test_public_service_directory_requires_active_and_approved_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        relation = request.url.path.rsplit("/", 1)[-1]
        if relation == "service_type":
            if "is_active" in request.url.params:
                return httpx.Response(200, json=[{"id": SERVICE_ID}])
            return httpx.Response(200, json=[{"id": SERVICE_ID, "is_active": True}])
        if relation == "party_capability":
            return httpx.Response(
                200,
                json=[
                    {
                        "marketplace_party_id": SELLER_ID,
                        "service_type_id": SERVICE_ID,
                    }
                ],
            )
        assert relation == "marketplace_party"
        return httpx.Response(200, json=[{"id": SELLER_ID}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        await acceptance.verify_public_service_directory(api)


@pytest.mark.anyio
async def test_public_service_directory_rejects_inactive_visibility() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json=[{"id": SERVICE_ID, "is_active": False}],
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        with pytest.raises(base.AcceptanceFailure) as error:
            await acceptance.verify_public_service_directory(api)
    assert error.value.classification == "service_directory_scope_violation"


@pytest.mark.anyio
async def test_seller_owner_capability_path_checks_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["marketplace_party_id"] == f"eq.{SELLER_ID}"
        if "authorization" not in request.headers:
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[
                {
                    "marketplace_party_id": SELLER_ID,
                    "service_type_id": SERVICE_ID,
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        await acceptance.verify_seller_own_capability(
            api,
            seller_session=build_session(),
            seller_party_id=SecretStr(SELLER_ID),
        )


@pytest.mark.anyio
async def test_furnishing_discovery_requires_every_locked_state_before_patch() -> None:
    requested = list(REQUEST_IDS)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[furnishing_row(state) for state in requested])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        fixtures = await acceptance.discover_furnishing_fixtures(
            api,
            customer_session=build_session(),
            customer_profile_id=SecretStr(CUSTOMER_ID),
        )
    assert {row.values["lifecycle_state"] for row in fixtures.editable_requests} == {
        "draft",
        "open",
    }
    assert {row.values["lifecycle_state"] for row in fixtures.locked_requests} == {
        "accepted",
        "withdrawn",
        "closed",
    }


@pytest.mark.anyio
async def test_missing_furnishing_fixture_fails_before_any_patch() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json=[furnishing_row("draft")])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        with pytest.raises(base.AcceptanceFailure) as error:
            await acceptance.discover_furnishing_fixtures(
                api,
                customer_session=build_session(),
                customer_profile_id=SecretStr(CUSTOMER_ID),
            )
    assert error.value.classification == "fixture_precondition_not_met"
    assert methods == ["GET"]


@pytest.mark.anyio
async def test_furnishing_noops_use_existing_values_and_check_after() -> None:
    records = {
        identifier: furnishing_row(state) for state, identifier in REQUEST_IDS.items()
    }
    patch_bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        identifier = request.url.params["id"].removeprefix("eq.")
        row = records[identifier]
        if request.method == "PATCH":
            body = json.loads(request.content)
            patch_bodies.append(body)
            if set(body) == {acceptance.FURNISHING_EDITABLE_PROBE_COLUMN} and row[
                "lifecycle_state"
            ] in {"draft", "open"}:
                return httpx.Response(
                    200,
                    json=[row],
                    headers={"Content-Range": "0-0/1"},
                )
            return httpx.Response(200, json=[], headers={"Content-Range": "*/0"})
        return httpx.Response(200, json=[row])

    fixtures = acceptance.Phase32CFixtures(
        editable_requests=(snapshot("draft"), snapshot("open")),
        locked_requests=tuple(
            snapshot(state) for state in acceptance.LOCKED_FURNISHING_STATES
        ),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        await acceptance.verify_furnishing_update_boundaries(
            api,
            customer_session=build_session(),
            fixtures=fixtures,
        )
    assert patch_bodies == [
        {"lifecycle_state": "draft"},
        {"coarse_location": None},
        {"lifecycle_state": "open"},
        {"coarse_location": None},
        {"coarse_location": None},
        {"coarse_location": None},
        {"coarse_location": None},
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["timeout", "malformed"])
async def test_public_projection_network_and_malformed_fail_closed(mode: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/rpc/" in request.url.path:
            return httpx.Response(403)
        if request.url.path.endswith("/review") and request.url.params.get(
            "select"
        ) in {
            "customer_profile_id",
            "target_service_request_id",
        }:
            return httpx.Response(403)
        if mode == "timeout":
            raise httpx.ReadTimeout("private", request=request)
        return httpx.Response(200, content=b"not-json")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        with pytest.raises(base.AcceptanceFailure) as error:
            await acceptance.verify_anonymous_review_boundary(api)
    expected = "upstream_unavailable" if mode == "timeout" else "malformed_response"
    assert error.value.classification == expected


def test_unexpected_failure_output_redacts_rows_tokens_uuids_and_comments(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = f"{TEST_ACCESS_TOKEN} {CUSTOMER_ID} private-review-comment"

    async def fail() -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(acceptance, "async_main", fail)
    assert acceptance.main() == 1
    output = capsys.readouterr().out
    assert output == (
        "check=live_phase_3_2c_acceptance actor=runner status=failed "
        "safe_error_classification=unexpected_internal_error\n"
    )
    assert secret not in output


def test_utility_has_no_data_post_delete_sql_or_service_role_path() -> None:
    source = Path(inspect.getsourcefile(acceptance) or "").read_text(encoding="utf-8")
    lower_source = source.lower()
    assert ".post(" not in lower_source
    assert ".delete(" not in lower_source
    assert "service_role" not in lower_source
    assert "supabase_secret" not in lower_source
    assert "sql editor" not in lower_source
    assert "base.probe_noop_patch" in source
    assert 'relation="public_review"' not in source
    assert "open_furnishing_request" not in source
    assert "withdraw_furnishing_request" not in source


def test_utility_uses_exact_furnishing_snapshot_and_safe_noop_column() -> None:
    assert acceptance.FURNISHING_REQUEST_FIELDS == (
        "id",
        "customer_profile_id",
        "address_id",
        "title",
        "requirements_description",
        "reference_image_urls",
        "budget_min",
        "budget_max",
        "requested_timing",
        "offer_deadline",
        "lifecycle_state",
        "created_at",
        "coarse_location",
    )
    assert acceptance.FURNISHING_EDITABLE_PROBE_COLUMN == "coarse_location"
