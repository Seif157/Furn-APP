"""Validated application configuration."""

import re
from typing import Annotated

from pydantic import Field, HttpUrl, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError


class Settings(BaseSettings):
    """Strict settings loaded from the process environment or a local `.env`."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        strict=True,
    )

    supabase_url: HttpUrl = Field(validation_alias="SUPABASE_URL")
    supabase_publishable_key: SecretStr = Field(
        validation_alias="SUPABASE_PUBLISHABLE_KEY"
    )
    supabase_auth_timeout_seconds: Annotated[float, Field(gt=0, le=30)] = Field(
        validation_alias="SUPABASE_AUTH_TIMEOUT_SECONDS"
    )

    @field_validator("supabase_url")
    @classmethod
    def require_https_supabase_url(cls, value: HttpUrl) -> HttpUrl:
        """Allow credentials to be sent only to an HTTPS endpoint."""

        if value.scheme != "https":
            raise ValueError("SUPABASE_URL must use HTTPS")
        return value

    @field_validator("supabase_publishable_key")
    @classmethod
    def require_publishable_key(cls, value: SecretStr) -> SecretStr:
        """Reject blank values and keys from other Supabase key classes."""

        raw_value = value.get_secret_value()
        if re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", raw_value) is None:
            raise ValueError("SUPABASE_PUBLISHABLE_KEY is malformed")
        return value


def load_settings() -> Settings:
    """Load settings while keeping configuration values out of startup errors."""

    try:
        return Settings()
    except (SettingsError, ValidationError):
        raise RuntimeError("Application configuration is invalid.") from None
