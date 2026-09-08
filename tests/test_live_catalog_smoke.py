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

    session = live_catalog_smoke.PasswordSession(
        access_token=SecretStr(TEST_ACCESS_TOKEN),
        refresh_token=SecretStr(TEST_REFRESH_TOKEN),
    )
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
