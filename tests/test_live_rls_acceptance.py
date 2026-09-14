"""Deterministic safety tests for the staged live RLS acceptance utility."""

import inspect
import json
from io import StringIO
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from scripts import live_rls_acceptance as acceptance

TEST_PUBLISHABLE_KEY = "sb_publishable_rls_acceptance_test_key"
TEST_ACCESS_TOKEN = "access-token-must-never-be-printed"
TEST_REFRESH_TOKEN = "refresh-token-must-never-be-printed"
TEST_PASSWORD = "password-must-never-be-printed"
SELLER_PARTY_ID = "11111111-1111-4111-8111-111111111111"
OWN_PRODUCT_ID = "22222222-2222-4222-8222-222222222222"
OTHER_PRODUCT_ID = "33333333-3333-4333-8333-333333333333"
OWN_CHILD_ID = "44444444-4444-4444-8444-444444444444"
OTHER_CHILD_ID = "55555555-5555-4555-8555-555555555555"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class TTYStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def build_settings() -> Settings:
    return Settings(
        SUPABASE_URL="https://testing-project.supabase.co",
        SUPABASE_PUBLISHABLE_KEY=TEST_PUBLISHABLE_KEY,
        SUPABASE_AUTH_TIMEOUT_SECONDS=5.0,
        _env_file=None,
    )


def build_session(token: str = TEST_ACCESS_TOKEN) -> acceptance.PasswordSession:
    return acceptance.PasswordSession(
        access_token=SecretStr(token),
        refresh_token=SecretStr(TEST_REFRESH_TOKEN),
    )


def build_snapshot(
    *,
    relation: str = "product",
    identifier: str = OWN_PRODUCT_ID,
    column: str = "description",
    value: object = "unchanged-business-value",
) -> acceptance.RecordSnapshot:
    fields = ("id", column)
    return acceptance.RecordSnapshot(
        relation=relation,
        fields=fields,
        identifier=SecretStr(identifier),
        values={"id": identifier, column: value},
    )


def test_refuses_noninteractive_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acceptance.sys, "stdin", StringIO())
    monkeypatch.setattr(acceptance.sys, "stderr", StringIO())

    with pytest.raises(acceptance.AcceptanceFailure) as error:
        acceptance.collect_interactive_secrets()

    assert error.value.classification == "secure_terminal_required"


def test_requires_exact_fake_branch_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acceptance.sys, "stdin", TTYStringIO())
    monkeypatch.setattr(acceptance.sys, "stderr", TTYStringIO())
    monkeypatch.setattr("builtins.input", lambda _prompt: "production")
    monkeypatch.setattr(
        acceptance.getpass,
        "getpass",
        lambda _prompt: pytest.fail("password input must not start"),
    )

    with pytest.raises(acceptance.AcceptanceFailure) as error:
        acceptance.collect_interactive_secrets()

    assert error.value.classification == "testing_branch_not_confirmed"


def test_credentials_are_required_and_secret_models_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passwords = iter((TEST_PASSWORD, f"seller-{TEST_PASSWORD}"))
    monkeypatch.setattr(acceptance.sys, "stdin", TTYStringIO())
    monkeypatch.setattr(acceptance.sys, "stderr", TTYStringIO())
    monkeypatch.setattr(
        "builtins.input", lambda _prompt: acceptance.TEST_BRANCH_CONFIRMATION
    )
    monkeypatch.setattr(acceptance.getpass, "getpass", lambda _prompt: next(passwords))

    secrets = acceptance.collect_interactive_secrets()

    assert secrets.model_dump() == {}
    assert secrets.model_dump_json() == "{}"
    assert TEST_PASSWORD not in repr(secrets)
    output = capsys.readouterr().out
    assert TEST_PASSWORD not in output
    assert "status=passed" in output


@pytest.mark.parametrize("name", sorted(acceptance.FORBIDDEN_SECRET_ENVIRONMENT_NAMES))
def test_refuses_service_role_or_secret_configuration(name: str) -> None:
    with pytest.raises(acceptance.AcceptanceFailure) as error:
        acceptance.reject_forbidden_secret_configuration({name: "never-read"})

    assert error.value.classification == "forbidden_secret_configuration"


@pytest.mark.anyio
async def test_authentication_uses_only_publishable_key_and_redacts_tokens() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/auth/v1/token"
        assert request.headers["apikey"] == TEST_PUBLISHABLE_KEY
        assert "service_role" not in " ".join(request.headers.values()).lower()
        assert json.loads(request.content) == {
            "email": acceptance.CUSTOMER_EMAIL,
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
        session = await acceptance.sign_in(
            client=client,
            settings=build_settings(),
            actor="customer",
            email=acceptance.CUSTOMER_EMAIL,
            password=SecretStr(TEST_PASSWORD),
        )

    assert session.model_dump() == {}
    assert TEST_ACCESS_TOKEN not in repr(session)
    assert TEST_REFRESH_TOKEN not in repr(session)


@pytest.mark.anyio
async def test_authentication_malformed_response_fails_closed() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(acceptance.AcceptanceFailure) as error:
            await acceptance.sign_in(
                client=client,
                settings=build_settings(),
                actor="seller",
                email=acceptance.SELLER_EMAIL,
                password=SecretStr(TEST_PASSWORD),
            )

    assert error.value.classification == "invalid_authentication_response"


def test_unexpected_errors_and_reports_do_not_leak_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_body = "upstream-body-with-uuid-and-token"

    async def fail() -> None:
        raise RuntimeError(secret_body)

    monkeypatch.setattr(acceptance, "async_main", fail)
    assert acceptance.main() == 1
    output = capsys.readouterr().out
    assert output == (
        "check=live_rls_acceptance actor=runner status=failed "
        "safe_error_classification=unexpected_internal_error\n"
    )
    assert secret_body not in output


@pytest.mark.anyio
async def test_public_catalogue_reads_use_full_allowlist_and_composite_key(
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["apikey"] == TEST_PUBLISHABLE_KEY
        seen[request.url.path.rsplit("/", 1)[-1]] = request.url.params["select"]
        if "category.is_active" in request.url.params:
            return httpx.Response(200, json=[{"id": OWN_PRODUCT_ID}])
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = acceptance.PostgrestAcceptanceClient(
            client=client,
            settings=build_settings(),
        )
        await acceptance.verify_public_catalogue_reads(
            api,
            session=None,
            actor="anonymous",
        )

    assert set(acceptance.PUBLIC_CATALOGUE_READS) <= seen.keys()
    assert seen["product_enrichment_assignment"] == "product_id,attribute_id"
    assert "id" not in seen["product_enrichment_assignment"].split(",")
    assert TEST_PUBLISHABLE_KEY not in capsys.readouterr().out


@pytest.mark.anyio
async def test_anonymous_private_reads_and_helpers_are_denied() -> None:
    seen_relations: set[str] = set()
    seen_helpers: set[str] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        name = request.url.path.rsplit("/", 1)[-1]
        if "/rpc/" in request.url.path:
            seen_helpers.add(name)
            return httpx.Response(403, json={"message": "not exposed"})
        seen_relations.add(name)
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = acceptance.PostgrestAcceptanceClient(
            client=client,
            settings=build_settings(),
        )
        await acceptance.verify_anonymous_denials(api)

    assert seen_relations == set(acceptance.PRIVATE_ANONYMOUS_RELATIONS)
    assert seen_helpers == set(acceptance.RESTRICTED_HELPERS)


@pytest.mark.anyio
async def test_customer_and_seller_helper_results_are_strict() -> None:
    results = {
        "is_admin": [False, False],
        "current_marketplace_party_id": [None, SELLER_PARTY_ID],
        "current_party_is_approved": [False, True],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        helper = request.url.path.rsplit("/", 1)[-1]
        result = results[helper].pop(0)
        if result is None:
            return httpx.Response(200, content=b"null")
        return httpx.Response(200, json=result)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = acceptance.PostgrestAcceptanceClient(
            client=client,
            settings=build_settings(),
        )
        await acceptance.verify_customer_helpers(api, session=build_session())
        party_id = await acceptance.verify_seller_helpers(
            api,
            session=build_session("seller-access-token"),
        )

    assert party_id.get_secret_value() == SELLER_PARTY_ID


@pytest.mark.anyio
async def test_denied_noop_accepts_empty_affected_rows_and_checks_after() -> None:
    target = build_snapshot()
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PATCH":
            assert request.headers["prefer"] == "return=representation,count=exact"
            assert json.loads(request.content) == {
                "description": target.values["description"]
            }
            return httpx.Response(200, json=[], headers={"Content-Range": "*/0"})
        return httpx.Response(200, json=[dict(target.values)])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = acceptance.PostgrestAcceptanceClient(
            client=client,
            settings=build_settings(),
        )
        await acceptance.probe_noop_patch(
            api,
            session=build_session(),
            actor="customer",
            expected=target,
            column="description",
            allowed=False,
            check="customer_product_denial",
        )

    assert methods == ["GET", "PATCH", "GET"]


@pytest.mark.anyio
async def test_column_level_approval_denial_uses_exact_existing_value() -> None:
    target = build_snapshot(
        relation="marketplace_party",
        identifier=SELLER_PARTY_ID,
        column="approval_state",
        value="approved",
    )
    patch_bodies: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            patch_bodies.append(json.loads(request.content))
            return httpx.Response(403, json={"message": "permission denied"})
        return httpx.Response(200, json=[dict(target.values)])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = acceptance.PostgrestAcceptanceClient(
            client=client,
            settings=build_settings(),
        )
        await acceptance.probe_noop_patch(
            api,
            session=build_session("seller-token"),
            actor="seller",
            expected=target,
            column="approval_state",
            allowed=False,
            check="seller_approval_state_denial",
        )

    assert patch_bodies == [{"approval_state": "approved"}]


@pytest.mark.anyio
async def test_unexpected_successful_forbidden_write_fails_after_cleanup_read() -> None:
    target = build_snapshot()
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PATCH":
            return httpx.Response(
                200,
                json=[dict(target.values)],
                headers={"Content-Range": "0-0/1"},
            )
        return httpx.Response(200, json=[dict(target.values)])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = acceptance.PostgrestAcceptanceClient(
            client=client,
            settings=build_settings(),
        )
        with pytest.raises(acceptance.AcceptanceFailure) as error:
            await acceptance.probe_noop_patch(
                api,
                session=build_session(),
                actor="customer",
                expected=target,
                column="description",
                allowed=False,
                check="customer_product_denial",
            )

    assert error.value.classification == "forbidden_write_succeeded"
    assert methods == ["GET", "PATCH", "GET"]


@pytest.mark.anyio
async def test_allowed_noop_requires_before_representation_and_after_equality() -> None:
    target = build_snapshot()
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PATCH":
            return httpx.Response(
                200,
                json=[dict(target.values)],
                headers={"Content-Range": "0-0/1"},
            )
        return httpx.Response(200, json=[dict(target.values)])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = acceptance.PostgrestAcceptanceClient(
            client=client,
            settings=build_settings(),
        )
        await acceptance.probe_noop_patch(
            api,
            session=build_session("seller-token"),
            actor="seller",
            expected=target,
            column="description",
            allowed=True,
            check="seller_own_product_noop",
        )

    assert methods == ["GET", "PATCH", "GET"]


@pytest.mark.anyio
async def test_changed_after_value_fails_closed() -> None:
    target = build_snapshot()
    get_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_count
        if request.method == "PATCH":
            return httpx.Response(
                200,
                json=[dict(target.values)],
                headers={"Content-Range": "0-0/1"},
            )
        get_count += 1
        values = dict(target.values)
        if get_count == 2:
            values["description"] = "unexpected-change"
        return httpx.Response(200, json=[values])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = acceptance.PostgrestAcceptanceClient(
            client=client,
            settings=build_settings(),
        )
        with pytest.raises(acceptance.AcceptanceFailure) as error:
            await acceptance.probe_noop_patch(
                api,
                session=build_session("seller-token"),
                actor="seller",
                expected=target,
                column="description",
                allowed=True,
                check="seller_own_product_noop",
            )

    assert error.value.classification == "business_values_changed"
    assert get_count == 2


@pytest.mark.anyio
@pytest.mark.parametrize("patch_mode", ["timeout", "malformed"])
async def test_patch_failure_still_performs_cleanup_read(patch_mode: str) -> None:
    target = build_snapshot()
    get_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_count
        if request.method == "PATCH":
            if patch_mode == "timeout":
                raise httpx.ReadTimeout("private timeout", request=request)
            return httpx.Response(200, content=b"not-json")
        get_count += 1
        return httpx.Response(200, json=[dict(target.values)])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = acceptance.PostgrestAcceptanceClient(
            client=client,
            settings=build_settings(),
        )
        with pytest.raises(acceptance.AcceptanceFailure) as error:
            await acceptance.probe_noop_patch(
                api,
                session=build_session(),
                actor="customer",
                expected=target,
                column="description",
                allowed=False,
                check="customer_product_denial",
            )

    expected_error = (
        "upstream_unavailable" if patch_mode == "timeout" else "malformed_response"
    )
    assert error.value.classification == expected_error
    assert get_count == 2


@pytest.mark.anyio
async def test_matrix_distinguishes_own_other_and_protected_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    own_product = build_snapshot(identifier=OWN_PRODUCT_ID)
    other_product = build_snapshot(identifier=OTHER_PRODUCT_ID)
    party = build_snapshot(
        relation="marketplace_party",
        identifier=SELLER_PARTY_ID,
        column="business_description",
    )
    own_child = build_snapshot(
        relation="product_color",
        identifier=OWN_CHILD_ID,
        column="color_value",
    )
    other_child = build_snapshot(
        relation="product_color",
        identifier=OTHER_CHILD_ID,
        column="color_value",
    )
    fixtures = acceptance.AcceptanceFixtures(
        seller_party=party,
        own_product=own_product,
        other_product=other_product,
        own_child=own_child,
        other_child=other_child,
    )
    calls: list[tuple[str, str, str, bool]] = []

    async def capture_probe(*_args: object, **kwargs: object) -> None:
        target = kwargs["expected"]
        assert isinstance(target, acceptance.RecordSnapshot)
        calls.append(
            (
                str(kwargs["actor"]),
                target.identifier.get_secret_value(),
                str(kwargs["column"]),
                bool(kwargs["allowed"]),
            )
        )

    monkeypatch.setattr(acceptance, "probe_noop_patch", capture_probe)
    await acceptance.run_noop_patch_matrix(
        None,  # type: ignore[arg-type]
        customer_session=build_session(),
        seller_session=build_session("seller-token"),
        fixtures=fixtures,
    )

    assert len(calls) == 9
    assert ("seller", OWN_PRODUCT_ID, "description", True) in calls
    assert ("seller", OTHER_PRODUCT_ID, "description", False) in calls
    assert ("seller", OWN_CHILD_ID, "color_value", True) in calls
    assert ("seller", OTHER_CHILD_ID, "color_value", False) in calls
    assert ("seller", SELLER_PARTY_ID, "approval_state", False) in calls
    assert ("seller", SELLER_PARTY_ID, "state_reason", False) in calls


@pytest.mark.anyio
async def test_financial_view_must_be_subset_of_visible_order_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/purchase_order"):
            return httpx.Response(200, json=[{"id": OWN_PRODUCT_ID}])
        return httpx.Response(200, json=[{"purchase_order_id": OWN_PRODUCT_ID}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = acceptance.PostgrestAcceptanceClient(
            client=client,
            settings=build_settings(),
        )
        await acceptance.verify_financial_view_scope(
            api,
            session=build_session(),
            actor="customer",
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "missing_relation", ["purchase_order", "order_financial_position"]
)
async def test_financial_fixture_insufficiency_fails_safely(
    missing_relation: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        relation = request.url.path.rsplit("/", 1)[-1]
        if relation == missing_relation:
            return httpx.Response(200, json=[])
        if relation == "purchase_order":
            return httpx.Response(200, json=[{"id": OWN_PRODUCT_ID}])
        return httpx.Response(200, json=[{"purchase_order_id": OWN_PRODUCT_ID}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = acceptance.PostgrestAcceptanceClient(
            client=client,
            settings=build_settings(),
        )
        with pytest.raises(acceptance.AcceptanceFailure) as error:
            await acceptance.verify_financial_view_scope(
                api,
                session=build_session(),
                actor="customer",
            )

    assert error.value.classification == "fixture_precondition_not_met"


@pytest.mark.anyio
async def test_fixture_discovery_failure_stops_before_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_result(*_args: object, **_kwargs: object) -> None:
        return None

    async def seller_result(*_args: object, **_kwargs: object) -> SecretStr:
        return SecretStr(SELLER_PARTY_ID)

    async def no_fixtures(*_args: object, **_kwargs: object) -> None:
        raise acceptance.AcceptanceFailure(
            check="fixture_discovery",
            actor="seller",
            classification="fixture_precondition_not_met",
        )

    async def patch_must_not_start(*_args: object, **_kwargs: object) -> None:
        pytest.fail("PATCH matrix started before fixture discovery completed")

    monkeypatch.setattr(acceptance, "verify_public_catalogue_reads", no_result)
    monkeypatch.setattr(acceptance, "verify_anonymous_denials", no_result)
    monkeypatch.setattr(acceptance, "verify_customer_helpers", no_result)
    monkeypatch.setattr(acceptance, "verify_seller_helpers", seller_result)
    monkeypatch.setattr(acceptance, "discover_acceptance_fixtures", no_fixtures)
    monkeypatch.setattr(acceptance, "run_noop_patch_matrix", patch_must_not_start)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: None)
    ) as client:
        with pytest.raises(acceptance.AcceptanceFailure) as error:
            await acceptance.run_acceptance_checks(
                settings=build_settings(),
                customer_session=build_session(),
                seller_session=build_session("seller-token"),
                client=client,
            )

    assert error.value.classification == "fixture_precondition_not_met"


def test_database_client_has_no_post_delete_rpc_mutation_or_sql_paths() -> None:
    source = Path(inspect.getsourcefile(acceptance) or "").read_text(encoding="utf-8")
    client_source = inspect.getsource(acceptance.PostgrestAcceptanceClient)

    assert source.count(".post(") == 1
    assert "/auth/v1/token" in source
    assert ".delete(" not in source.lower()
    assert "rpc/" in client_source
    assert 'method: Literal["GET", "PATCH"]' in client_source
    assert ".post(" not in client_source.lower()
    assert ".delete(" not in client_source.lower()
    assert ".insert(" not in client_source.lower()
    assert ".execute(" not in client_source.lower()
