"""Read the live service directory with the caller's own token.

The service types are marketplace data: a customer's "my wardrobe door is
broken" may only ever be matched to a service this marketplace actually offers.
Nothing here invents one, and row-level security still decides what is visible
(Phase 3.2C: only active service types are public).

The read is deliberately tolerant about the shape it gets back. Unlike the
catalogue, this table's columns are not recorded in this repository's evidence,
so the gateway asks for the whole row and looks for a display name among the
names such a column plausibly has. If it finds none, it reports that it found
none; it never labels a service with its id or with a guess.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict

from app.auth.models import AuthenticatedRequestContext
from app.config import Settings

MAX_SERVICE_TYPES = 100

NAME_COLUMNS = ("name", "title", "label", "service_name", "display_name")
DESCRIPTION_COLUMNS = ("description", "details", "summary", "notes")


class ServiceType(BaseModel):
    """One real, active service the marketplace offers."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    name: str
    description: str | None = None


class ServiceDirectoryGateway(Protocol):
    async def list_active(
        self, *, authenticated_request: AuthenticatedRequestContext
    ) -> tuple[ServiceType, ...]:
        """Return the active service types, or an empty tuple."""


def _first_text(row: dict[str, object], columns: tuple[str, ...]) -> str | None:
    for column in columns:
        value = row.get(column)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_service_rows(rows: object) -> tuple[ServiceType, ...]:
    """Validate untrusted PostgREST rows, dropping anything unusable."""

    if not isinstance(rows, list):
        return ()
    services: list[ServiceType] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("is_active") is False:
            continue
        name = _first_text(row, NAME_COLUMNS)
        if name is None:
            continue
        try:
            identifier = UUID(str(row.get("id")))
        except (ValueError, TypeError):
            continue
        services.append(
            ServiceType(
                id=identifier,
                name=name,
                description=_first_text(row, DESCRIPTION_COLUMNS),
            )
        )
    return tuple(services)


class SupabaseServiceDirectoryGateway:
    """Fetch the active service directory through PostgREST."""

    def __init__(self, *, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._endpoint = (
            f"{str(settings.supabase_url).rstrip('/')}/rest/v1/service_type"
        )
        self._publishable_key = settings.supabase_publishable_key.get_secret_value()
        self._timeout_seconds = settings.supabase_auth_timeout_seconds

    async def list_active(
        self, *, authenticated_request: AuthenticatedRequestContext
    ) -> tuple[ServiceType, ...]:
        try:
            response = await self._client.get(
                self._endpoint,
                params={
                    # The column names are not recorded anywhere in this
                    # repository; row-level security, not this projection, is
                    # what keeps inactive services out of the answer.
                    "select": "*",
                    "is_active": "eq.true",
                    "order": "id.asc",
                    "limit": str(MAX_SERVICE_TYPES),
                },
                headers={
                    "Accept": "application/json",
                    "apikey": self._publishable_key,
                    "Authorization": (
                        "Bearer "
                        f"{authenticated_request.access_token.get_secret_value()}"
                    ),
                },
                timeout=self._timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.RequestError):
            return ()
        if response.status_code != httpx.codes.OK:
            return ()
        try:
            return parse_service_rows(response.json())
        except ValueError:
            return ()
