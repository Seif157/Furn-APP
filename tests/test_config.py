"""Tests for strict Supabase application settings."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import AISettings, Settings, load_ai_settings, load_settings

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


AI_SETTINGS_KEYS = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_TIMEOUT_SECONDS",
    "GEMINI_BASE_URL",
    "GEMINI_THINKING_BUDGET",
)


def build_ai_settings(**overrides: Any) -> AISettings:
    configuration: dict[str, Any] = {"GEMINI_API_KEY": "test-gemini-key"}
    return AISettings(_env_file=None, **(configuration | overrides))


def test_ai_settings_are_optional_as_a_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in AI_SETTINGS_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    settings = load_ai_settings()

    assert settings.gemini_enabled is False
    assert settings.gemini_api_key is None
    assert settings.gemini_model == "gemini-3.6-flash"
    assert settings.gemini_timeout_seconds == 20.0
    assert settings.gemini_thinking_budget == 0


def test_a_configured_key_enables_the_ai_path() -> None:
    assert build_ai_settings().gemini_enabled is True


@pytest.mark.parametrize(
    "key",
    ["", "   ", "short", "key with spaces", "key\nx-goog-user: forged"],
)
def test_ai_settings_reject_keys_that_could_forge_a_header(key: str) -> None:
    with pytest.raises(ValidationError):
        build_ai_settings(GEMINI_API_KEY=key)


@pytest.mark.parametrize(
    "model",
    ["", "../../v1/models/other", "gemini flash", "a" * 65, "model?key=leak"],
)
def test_ai_settings_reject_models_that_are_not_one_path_segment(model: str) -> None:
    with pytest.raises(ValidationError):
        build_ai_settings(GEMINI_MODEL=model)


def test_ai_settings_reject_a_plaintext_base_url() -> None:
    with pytest.raises(ValidationError):
        build_ai_settings(GEMINI_BASE_URL="http://generativelanguage.googleapis.com")


@pytest.mark.parametrize("timeout", [0, -1, 61])
def test_ai_settings_reject_invalid_timeouts(timeout: int) -> None:
    with pytest.raises(ValidationError):
        build_ai_settings(GEMINI_TIMEOUT_SECONDS=timeout)


@pytest.mark.parametrize("budget", [-1, 24577])
def test_ai_settings_reject_invalid_thinking_budgets(budget: int) -> None:
    with pytest.raises(ValidationError):
        build_ai_settings(GEMINI_THINKING_BUDGET=budget)


def test_the_api_key_never_appears_in_a_repr() -> None:
    settings = build_ai_settings(GEMINI_API_KEY="super-secret-gemini-key")

    assert "super-secret-gemini-key" not in repr(settings)
    assert "super-secret-gemini-key" not in str(settings)


def test_load_ai_settings_uses_a_safe_startup_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "key with spaces")

    with pytest.raises(
        RuntimeError,
        match=r"^AI provider configuration is invalid\.$",
    ):
        load_ai_settings()
