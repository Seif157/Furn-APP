"""Validated application configuration."""

import re
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError

# Verified against the live API on 2026-09-17. gemini-2.5-flash answers a model
# listing but returns 404 on generateContent for keys created after its
# retirement, and Google's own error names gemini-3.6-flash as the replacement.
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
# Measured on 2026-09-18 rendering a planned room from three real product
# photos: this model and nano-banana-pro-preview both reproduced every product
# and the right counts, but this one took 14.5 s against 29 s and is a stable
# release rather than a preview. It did delete existing furniture when asked to
# edit a customer's own room photo, which is why room photos are not accepted.
DEFAULT_GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
HOSTNAME_PATTERN = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9-]{1,63})+")
# The model name is interpolated into the request path, and the API key into a
# request header. Both alphabets are deliberately narrow so neither value can
# introduce a path segment, a query string, or a header separator.
GEMINI_MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
GEMINI_API_KEY_PATTERN = re.compile(r"[\x21-\x7e]{8,256}")


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
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )
    supabase_secret_key: SecretStr | None = Field(
        default=None, validation_alias="SUPABASE_SECRET_KEY"
    )
    """The server-only Supabase secret key. It bypasses row-level security, so
    exactly one component may use it: the cart gateway, to create a customer's
    one cart (the 3.2D design forbids the client from inserting carts). Every
    other request still runs as the signed-in user. Optional: without it the
    app starts and only POST /v1/cart refuses."""

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

    @field_validator("supabase_secret_key")
    @classmethod
    def require_secret_key(cls, value: SecretStr | None) -> SecretStr | None:
        """Accept only a new-style secret key; never a legacy JWT or a mix-up."""

        if value is None:
            return None
        if re.fullmatch(r"sb_secret_[A-Za-z0-9_-]+", value.get_secret_value()) is None:
            raise ValueError("SUPABASE_SECRET_KEY is malformed")
        return value


class AISettings(BaseSettings):
    """Optional AI provider settings, loaded independently of Supabase.

    Every field has a default, so an instance with no AI configuration still
    starts and still serves auth and catalogue. Only the AI path is refused,
    and ``gemini_enabled`` is the single place that decides.
    """

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        strict=True,
    )

    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias="GEMINI_API_KEY"
    )
    gemini_model: str = Field(
        default=DEFAULT_GEMINI_MODEL, validation_alias="GEMINI_MODEL"
    )
    gemini_timeout_seconds: Annotated[float, Field(gt=0, le=60)] = Field(
        default=20.0, validation_alias="GEMINI_TIMEOUT_SECONDS"
    )
    gemini_base_url: HttpUrl = Field(
        default=HttpUrl(DEFAULT_GEMINI_BASE_URL), validation_alias="GEMINI_BASE_URL"
    )
    gemini_thinking_budget: Annotated[int, Field(ge=0, le=24576)] = Field(
        default=0, validation_alias="GEMINI_THINKING_BUDGET"
    )
    """Reasoning tokens allowed per call.

    Zero for requirement extraction: the task is short and mechanical, and
    reasoning tokens are charged against the same output cap as the answer.
    Measured on 2026-09-17, the identical request spent 1908 reasoning tokens
    with the field absent, overran the cap, and came back truncated; with the
    budget at zero it spent none and answered correctly.

    Not every model accepts the field. Some reject the whole request with
    INVALID_ARGUMENT, so a model change may mean removing it rather than
    tuning it.
    """

    gemini_image_model: str = Field(
        default=DEFAULT_GEMINI_IMAGE_MODEL, validation_alias="GEMINI_IMAGE_MODEL"
    )
    """Model that renders room previews. Separate because image generation is a
    different model family with different cost and latency."""
    gemini_image_timeout_seconds: Annotated[float, Field(gt=0, le=180)] = Field(
        default=90.0, validation_alias="GEMINI_IMAGE_TIMEOUT_SECONDS"
    )
    """Measured on 2026-09-18 at 10 to 19 seconds per image, so far above the
    text timeout."""
    image_reference_hosts: str = Field(
        default="images.unsplash.com", validation_alias="IMAGE_REFERENCE_HOSTS"
    )
    """Comma-separated hosts the server may fetch product photos from.

    Rendering a room preview means fetching each product's photo server-side,
    and those URLs are seller-controlled catalogue data. Without an allowlist a
    seller could point an image at an internal address and have this server
    request it. The Supabase project host is always allowed in addition.
    """

    rate_limit_search_per_minute: Annotated[int, Field(ge=1, le=1000)] = Field(
        default=20, validation_alias="RATE_LIMIT_SEARCH_PER_MINUTE"
    )
    rate_limit_room_plan_per_minute: Annotated[int, Field(ge=1, le=1000)] = Field(
        default=10, validation_alias="RATE_LIMIT_ROOM_PLAN_PER_MINUTE"
    )
    rate_limit_room_image_per_hour: Annotated[int, Field(ge=1, le=1000)] = Field(
        default=20, validation_alias="RATE_LIMIT_ROOM_IMAGE_PER_HOUR"
    )
    """Per signed-in user. A preview costs far more than a text call, so it is
    limited per hour rather than per minute."""
    ai_cache_ttl_seconds: Annotated[float, Field(ge=0, le=86400)] = Field(
        default=900.0, validation_alias="AI_CACHE_TTL_SECONDS"
    )
    """How long a parsed sentence or a rendered preview is reused. Zero turns
    caching off. See app/core/cache.py for why sharing entries is safe."""

    @property
    def gemini_enabled(self) -> bool:
        """Whether a key is present, which is the only switch for the AI path."""

        return self.gemini_api_key is not None

    @property
    def reference_hosts(self) -> frozenset[str]:
        return frozenset(
            host.strip().lower()
            for host in self.image_reference_hosts.split(",")
            if host.strip()
        )

    @field_validator("image_reference_hosts")
    @classmethod
    def require_plain_hostnames(cls, value: str) -> str:
        for host in (part.strip() for part in value.split(",")):
            if host and HOSTNAME_PATTERN.fullmatch(host.lower()) is None:
                raise ValueError("IMAGE_REFERENCE_HOSTS is malformed")
        return value

    @field_validator("gemini_api_key")
    @classmethod
    def require_header_safe_key(cls, value: SecretStr | None) -> SecretStr | None:
        """Reject blanks and any byte that could forge an extra request header."""

        if value is None:
            return None
        if GEMINI_API_KEY_PATTERN.fullmatch(value.get_secret_value()) is None:
            raise ValueError("GEMINI_API_KEY is malformed")
        return value

    @field_validator("gemini_model", "gemini_image_model")
    @classmethod
    def require_path_safe_model(cls, value: str) -> str:
        """Keep the model name a single, literal URL path segment."""

        if GEMINI_MODEL_PATTERN.fullmatch(value) is None:
            raise ValueError("GEMINI_MODEL is malformed")
        return value

    @field_validator("gemini_base_url")
    @classmethod
    def require_https_base_url(cls, value: HttpUrl) -> HttpUrl:
        """Allow the API key to be sent only to an HTTPS endpoint."""

        if value.scheme != "https":
            raise ValueError("GEMINI_BASE_URL must use HTTPS")
        return value


def load_settings() -> Settings:
    """Load settings while keeping configuration values out of startup errors."""

    try:
        return Settings()
    except (SettingsError, ValidationError):
        raise RuntimeError("Application configuration is invalid.") from None


def load_ai_settings() -> AISettings:
    """Load AI settings, keeping provider credentials out of startup errors."""

    try:
        return AISettings()
    except (SettingsError, ValidationError):
        raise RuntimeError("AI provider configuration is invalid.") from None
