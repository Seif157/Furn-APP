"""Tests for strict Supabase application settings."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings, load_settings

VALID_CONFIGURATION: dict[str, Any] = {
    "SUPABASE_URL": "https://test-project.supabase.co",
    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test_key_123",
    "SUPABASE_AUTH_TIMEOUT_SECONDS": 5.0,
}


def build_settings(**overrides: Any) -> Settings:
    configuration = VALID_CONFIGURATION | overrides
    return Settings(_env_file=None, **configuration)


def clear_supabase_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in VALID_CONFIGURATION:
        monkeypatch.delenv(name, raising=False)


def test_settings_read_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv(
        "SUPABASE_PUBLISHABLE_KEY",
        "sb_publishable_test_key_123",
    )
    monkeypatch.setenv("SUPABASE_AUTH_TIMEOUT_SECONDS", "5")

    settings = Settings(_env_file=None)

    assert settings.supabase_url.scheme == "https"
    assert settings.supabase_auth_timeout_seconds == 5.0


def test_settings_reject_missing_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_supabase_environment(monkeypatch)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_reject_non_https_url() -> None:
    with pytest.raises(ValidationError):
        build_settings(SUPABASE_URL="http://test-project.supabase.co")


def test_settings_reject_wrong_key_class() -> None:
    with pytest.raises(ValidationError):
        build_settings(SUPABASE_PUBLISHABLE_KEY="service_role_not_allowed")


def test_settings_ignore_forbidden_unmodeled_key_classes() -> None:
    settings = Settings(
        _env_file=None,
        **VALID_CONFIGURATION,
        SUPABASE_SECRET_KEY="secret-key-must-not-be-loaded",
        SUPABASE_JWKS_URL="https://example.invalid/jwks.json",
    )

    assert not hasattr(settings, "supabase_secret_key")
    assert not hasattr(settings, "supabase_jwks_url")


@pytest.mark.parametrize("timeout", [0, -1, 31])
def test_settings_reject_invalid_timeout(timeout: int) -> None:
    with pytest.raises(ValidationError):
        build_settings(SUPABASE_AUTH_TIMEOUT_SECONDS=timeout)


def test_load_settings_uses_safe_startup_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clear_supabase_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(
        RuntimeError,
        match=r"^Application configuration is invalid\.$",
    ):
        load_settings()
