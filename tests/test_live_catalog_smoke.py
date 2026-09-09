"""Safety tests for the interactive live-catalogue smoke utility."""

import json
from io import StringIO

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from scripts import live_catalog_smoke

TEST_PUBLISHABLE_KEY = "sb_publishable_live_smoke_test_key"
TEST_ACCESS_TOKEN = "access-token-must-remain-private"
TEST_REFRESH_TOKEN = "refresh-token-must-remain-private"
RAW_PRODUCT_DATA = "private-product-name-and-image-url-must-remain-private"


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


def build_test_session() -> live_catalog_smoke.PasswordSession:
    return live_catalog_smoke.PasswordSession(
        access_token=SecretStr(TEST_ACCESS_TOKEN),
        refresh_token=SecretStr(TEST_REFRESH_TOKEN),
    )


def install_diagnostic_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: httpx.MockTransport,
) -> None:
    async_client = httpx.AsyncClient

    def build_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        assert not args
        assert not kwargs
        return async_client(transport=handler)

    monkeypatch.setattr(live_catalog_smoke.httpx, "AsyncClient", build_client)


def test_credential_input_refuses_noninteractive_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_catalog_smoke.sys, "stdin", StringIO("hidden@example.com"))
    monkeypatch.setattr(live_catalog_smoke.sys, "stderr", StringIO())

    with pytest.raises(live_catalog_smoke.SmokeFailure) as error:
        live_catalog_smoke.collect_credentials()

    assert error.value.check == "credential_input"
    assert error.value.classification == "secure_terminal_required"


def test_report_output_contains_only_safe_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    live_catalog_smoke.report_result(
        check="catalogue_list",
        status="passed",
        http_status=200,
        product_count=2,
    )

    assert capsys.readouterr().out == (
        "check=catalogue_list status=passed http_status=200 product_count=2\n"
    )


@pytest.mark.anyio
async def test_password_sign_in_uses_low_privilege_key_and_redacts_tokens() -> None:
    email = "test-user@example.com"
    password = "password-must-remain-private"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/auth/v1/token"
        assert request.url.params["grant_type"] == "password"
        assert request.headers["apikey"] == TEST_PUBLISHABLE_KEY
        assert json.loads(request.content) == {
            "email": email,
            "password": password,
        }
        return httpx.Response(
            200,
            json={
                "access_token": TEST_ACCESS_TOKEN,
                "refresh_token": TEST_REFRESH_TOKEN,
                "user": {"id": "not-used-by-the-script"},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        session, status_code = await live_catalog_smoke.sign_in(
            client=client,
            settings=build_test_settings(),
            email=email,
            password=password,
        )

    assert status_code == 200
    assert session.model_dump() == {}
    assert session.model_dump_json() == "{}"
    assert TEST_ACCESS_TOKEN not in repr(session)
    assert TEST_REFRESH_TOKEN not in repr(session)


def test_unexpected_error_output_does_not_include_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_exception_text = "private-token-and-upstream-body"

    async def fail_safely() -> None:
        raise RuntimeError(private_exception_text)

    monkeypatch.setattr(live_catalog_smoke, "async_main", fail_safely)

    assert live_catalog_smoke.main() == 1
    output = capsys.readouterr().out
    assert output == (
        "check=live_smoke status=failed "
        "safe_error_classification=unexpected_internal_error\n"
    )
    assert private_exception_text not in output


@pytest.mark.anyio
async def test_empty_catalogue_checks_report_only_aggregate_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_paths = {
        "/rest/v1/product",
        "/rest/v1/marketplace_party",
        "/rest/v1/category",
        "/rest/v1/product_color",
    }
    seen_paths: set[str] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "HEAD"
        assert request.headers["apikey"] == TEST_PUBLISHABLE_KEY
        assert request.headers["authorization"] == f"Bearer {TEST_ACCESS_TOKEN}"
        assert request.headers["prefer"] == "count=exact"
        seen_paths.add(request.url.path)
        return httpx.Response(200, headers={"Content-Range": "0-0/3"})

    session = build_test_session()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await live_catalog_smoke.count_eligible_source_rows(
            client=client,
            settings=build_test_settings(),
            session=session,
        )

    assert seen_paths == expected_paths
    output = capsys.readouterr().out
    assert output.count("status=passed") == 4
    assert output.count("product_count=3") == 4
    assert TEST_ACCESS_TOKEN not in output
    assert TEST_PUBLISHABLE_KEY not in output


def test_catalogue_diagnostic_stages_are_cumulative_and_constraint_hinted() -> None:
    stages = live_catalog_smoke.DIAGNOSTIC_STAGES
    root_columns = live_catalog_smoke.DIAGNOSTIC_ROOT_COLUMNS
    root_stages = live_catalog_smoke.DIAGNOSTIC_ROOT_COLUMN_STAGES

    assert tuple(stage.name for stage in root_stages) == tuple(
        f"root_product.{column}" for column in root_columns
    )
    for index, stage in enumerate(root_stages, start=1):
        assert stage.select == ",".join(root_columns[:index])
        assert stage.relationship_candidate == f"product.{root_columns[index - 1]}"
    assert tuple(stage.name for stage in stages[len(root_stages) :]) == (
        "root_product",
        "category_relationship",
        "marketplace_party_relationship",
        "product_color_relationship",
        "product_image_relationship",
        "enrichment_assignment_relationship",
        "enrichment_assignment_attribute_id",
        "enrichment_assignment_confirmation_state",
        "enrichment_assignment_filter",
        "enrichment_attribute_relationship",
        "enrichment_attribute_id",
        "enrichment_attribute_attribute_kind",
        "enrichment_attribute_attribute_value",
        "production_filters_and_ordering",
    )
    expected_hints = (
        "product_category_fk",
        "product_party_fk",
        "product_color_product_fk",
        "product_image_product_fk",
        "product_enrichment_assignment_product_fk",
        "product_enrichment_assignment_attribute_fk",
    )
    for hint in expected_hints:
        assert any(hint in stage.select for stage in stages[:-1])
    for stage in stages[len(root_stages) : -1]:
        assert live_catalog_smoke.DIAGNOSTIC_ROOT_SELECT in stage.select
    assert stages[-1].select == live_catalog_smoke.CATALOG_SELECT
    assert stages[-1].use_production_params is True


def test_enrichment_diagnostics_probe_only_verified_fields_cumulatively() -> None:
    stages = {stage.name: stage for stage in live_catalog_smoke.DIAGNOSTIC_STAGES}

    assert stages["enrichment_assignment_relationship"].select.endswith(
        "product_enrichment_assignment_product_fk(product_id)"
    )
    assert stages["enrichment_assignment_attribute_id"].select.endswith(
        "product_enrichment_assignment_product_fk(product_id,attribute_id)"
    )
    assert stages["enrichment_assignment_confirmation_state"].select.endswith(
        "product_enrichment_assignment_product_fk("
        "product_id,attribute_id,confirmation_state)"
    )
    assert stages["enrichment_assignment_filter"].query_params == (
        ("enrichment_assignments.confirmation_state", "eq.party_confirmed"),
    )
    assert stages["enrichment_attribute_relationship"].select.endswith(
        "product_enrichment_assignment_attribute_fk())"
    )
    assert stages["enrichment_attribute_id"].select.endswith(
        "product_enrichment_assignment_attribute_fk(id))"
    )
    assert stages["enrichment_attribute_attribute_kind"].select.endswith(
        "product_enrichment_assignment_attribute_fk(id,attribute_kind))"
    )
    assert stages["enrichment_attribute_attribute_value"].select.endswith(
        "product_enrichment_assignment_attribute_fk(id,attribute_kind,attribute_value))"
    )
    assert all(
        "proposed_at" not in stage.select
        for stage in live_catalog_smoke.DIAGNOSTIC_STAGES
    )


@pytest.mark.anyio
async def test_enrichment_diagnostic_adds_filter_after_assignment_fields(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    install_diagnostic_transport(monkeypatch, transport)

    await live_catalog_smoke.diagnose_catalogue_integration(
        settings=build_test_settings(),
        session=build_test_session(),
    )

    assignment_requests = [
        request
        for request in requests
        if request.url.params["select"]
        == live_catalog_smoke.DIAGNOSTIC_ASSIGNMENTS_SELECT
    ]
    assert len(assignment_requests) == 2
    assert "enrichment_assignments.confirmation_state" not in (
        assignment_requests[0].url.params
    )
    assert (
        assignment_requests[1].url.params["enrichment_assignments.confirmation_state"]
        == "eq.party_confirmed"
    )

    nested_selects = {
        live_catalog_smoke.DIAGNOSTIC_ATTRIBUTE_RELATION_SELECT,
        live_catalog_smoke.DIAGNOSTIC_ATTRIBUTE_ID_SELECT,
        live_catalog_smoke.DIAGNOSTIC_ATTRIBUTE_KIND_SELECT,
        live_catalog_smoke.DIAGNOSTIC_ATTRIBUTE_SELECT,
    }
    nested_requests = [
        request
        for request in requests
        if request.url.params["select"] in nested_selects
    ]
    assert len(nested_requests) == 4
    assert all(
        request.url.params["enrichment_assignments.confirmation_state"]
        == "eq.party_confirmed"
        for request in nested_requests
    )
    capsys.readouterr()


@pytest.mark.anyio
async def test_catalogue_diagnostic_reports_only_safe_relationship_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/rest/v1/product"
        assert request.url.params["limit"] == "1"
        assert request.headers["apikey"] == TEST_PUBLISHABLE_KEY
        assert request.headers["authorization"] == f"Bearer {TEST_ACCESS_TOKEN}"
        if (
            request.url.params["select"]
            != live_catalog_smoke.DIAGNOSTIC_CATEGORY_SELECT
        ):
            assert set(request.url.params) == {"select", "limit"}
            return httpx.Response(200, json=[])
        return httpx.Response(
            300,
            json={
                "code": "PGRST201",
                "message": (
                    f"{RAW_PRODUCT_DATA} {TEST_ACCESS_TOKEN} "
                    "product_category_fk product_legacy_category_fk"
                ),
                "details": (
                    "product_category_fk product_legacy_category_fk "
                    f"{TEST_PUBLISHABLE_KEY}"
                ),
            },
        )

    transport = httpx.MockTransport(handler)
    install_diagnostic_transport(monkeypatch, transport)

    await live_catalog_smoke.diagnose_catalogue_integration(
        settings=build_test_settings(),
        session=build_test_session(),
    )

    output = capsys.readouterr().out
    output_lines = output.splitlines()
    assert len(requests) == len(live_catalog_smoke.DIAGNOSTIC_ROOT_COLUMN_STAGES) + 2
    assert output_lines[-2:] == [
        "stage=root_product status=passed http_status=200 "
        "relationship_candidate=product",
        "stage=category_relationship status=failed http_status=300 "
        "relationship_candidate=product_category_fk|product_legacy_category_fk "
        "postgrest_error_code=PGRST201",
    ]
    assert RAW_PRODUCT_DATA not in output
    assert TEST_ACCESS_TOKEN not in output
    assert TEST_REFRESH_TOKEN not in output
    assert TEST_PUBLISHABLE_KEY not in output


@pytest.mark.anyio
async def test_catalogue_diagnostic_isolates_undefined_root_column(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests: list[httpx.Request] = []
    failing_select = "id,name,description,price,discount_price,width_cm"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.params["limit"] == "1"
        if request.url.params["select"] != failing_select:
            return httpx.Response(200, json=[])
        return httpx.Response(
            400,
            json={
                "code": "42703",
                "message": f"{RAW_PRODUCT_DATA} {TEST_ACCESS_TOKEN}",
            },
        )

    transport = httpx.MockTransport(handler)
    install_diagnostic_transport(monkeypatch, transport)

    await live_catalog_smoke.diagnose_catalogue_integration(
        settings=build_test_settings(),
        session=build_test_session(),
    )

    output = capsys.readouterr().out
    assert len(requests) == 6
    assert output.splitlines()[-1] == (
        "stage=root_product.width_cm status=failed http_status=400 "
        "relationship_candidate=product.width_cm postgrest_error_code=42703"
    )
    assert RAW_PRODUCT_DATA not in output
    assert TEST_ACCESS_TOKEN not in output
    assert TEST_PUBLISHABLE_KEY not in output


def test_postgrest_error_metadata_returns_only_code_and_safe_constraint() -> None:
    response = httpx.Response(
        400,
        json={
            "code": "PGRST200",
            "message": RAW_PRODUCT_DATA,
            "details": "product_category_fk",
        },
    )

    actual_code, candidate = live_catalog_smoke.postgrest_error_metadata(
        response,
        fallback_candidate="safe_relationship_candidate",
    )

    assert actual_code == "PGRST200"
    assert candidate == "product_category_fk"


@pytest.mark.anyio
async def test_catalogue_diagnostic_identifies_pydantic_type_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        assert request.url.params["limit"] == "1"
        if call_count < len(live_catalog_smoke.DIAGNOSTIC_STAGES):
            return httpx.Response(200, json=[])
        expected_params = live_catalog_smoke.catalogue_query_params()
        for name, value in expected_params.items():
            assert request.url.params[name] == value
        assert "offset" not in request.url.params
        return httpx.Response(
            200,
            json=[{"id": 123, "name": RAW_PRODUCT_DATA}],
        )

    transport = httpx.MockTransport(handler)
    install_diagnostic_transport(monkeypatch, transport)

    await live_catalog_smoke.diagnose_catalogue_integration(
        settings=build_test_settings(),
        session=build_test_session(),
    )

    output = capsys.readouterr().out
    assert call_count == len(live_catalog_smoke.DIAGNOSTIC_STAGES)
    assert "stage=pydantic_models status=failed http_status=200" in output
    assert "field_path=$[0].id" in output
    assert "expected_json_type=string" in output
    assert "received_json_type=number" in output
    assert RAW_PRODUCT_DATA not in output
    assert TEST_ACCESS_TOKEN not in output
    assert TEST_PUBLISHABLE_KEY not in output


@pytest.mark.anyio
async def test_catalogue_diagnostic_distinguishes_transformation_rejection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    class ValidatingAdapter:
        def validate_json(self, _content: bytes, *, strict: bool) -> tuple[object]:
            assert strict is True
            return (object(),)

    transport = httpx.MockTransport(handler)
    install_diagnostic_transport(monkeypatch, transport)
    monkeypatch.setattr(
        live_catalog_smoke,
        "_DIAGNOSTIC_PRODUCTS_ADAPTER",
        ValidatingAdapter(),
    )
    monkeypatch.setattr(
        live_catalog_smoke,
        "build_product_response",
        lambda _product: None,
    )

    await live_catalog_smoke.diagnose_catalogue_integration(
        settings=build_test_settings(),
        session=build_test_session(),
    )

    output = capsys.readouterr().out
    assert "stage=pydantic_models status=passed http_status=200" in output
    assert "stage=transformation_logic status=failed http_status=200" in output
    assert TEST_ACCESS_TOKEN not in output
    assert TEST_PUBLISHABLE_KEY not in output
