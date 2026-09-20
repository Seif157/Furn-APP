"""Find or create the caller's one cart.

The 3.2D security design removes INSERT on `cart` from clients: each customer
has exactly one cart (UNIQUE customer_profile_id), created by the server. This
module is the server side of that rule, split so the secret key's reach is as
small as it can be:

  CustomerCartReader  runs as the signed-in user, with their own token, so
                      row-level security decides what it sees. It finds the
                      caller's customer profile and existing cart.

  CartCreator         the only code that holds the Supabase secret key. It can
                      do one thing: insert a cart row for a customer profile id
                      that the reader has already established belongs to the
                      caller. It takes no other input and reads nothing.

The profile id is never taken from the client. The secret key is never logged,
never placed in an error, and never sent anywhere but this project's own
Supabase REST endpoint.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from app.auth.models import AuthenticatedRequestContext
from app.config import Settings


class CartServiceUnavailableError(Exception):
    pass


class CartUpstreamError(Exception):
    pass


class _IdRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID


_ID_ROWS = TypeAdapter(tuple[_IdRow, ...])


def _ids(response: httpx.Response) -> tuple[UUID, ...]:
    if response.status_code >= 500 or response.status_code == 429:
        raise CartServiceUnavailableError
    if response.status_code not in (httpx.codes.OK, httpx.codes.CREATED):
        raise CartUpstreamError
    try:
        return tuple(row.id for row in _ID_ROWS.validate_json(response.content))
    except ValidationError:
        raise CartUpstreamError from None


class CustomerCartReader(Protocol):
    async def profile_id(
        self, authenticated_request: AuthenticatedRequestContext
    ) -> UUID | None: ...

    async def cart_id(
        self,
        authenticated_request: AuthenticatedRequestContext,
        profile_id: UUID,
    ) -> UUID | None: ...


class CartCreator(Protocol):
    async def create(self, profile_id: UUID) -> UUID | None:
        """The new cart's id, or None if one already existed (a race)."""
        ...


class SupabaseCustomerCartReader:
    def __init__(self, *, client: httpx.AsyncClient, settings: Settings) -> None:
        base = str(settings.supabase_url).rstrip("/")
        self._client = client
        self._profiles = f"{base}/rest/v1/customer_profile"
        self._carts = f"{base}/rest/v1/cart"
        self._publishable_key = settings.supabase_publishable_key.get_secret_value()
        self._timeout = settings.supabase_auth_timeout_seconds

    async def _get(
        self,
        url: str,
        params: dict[str, str],
        authenticated_request: AuthenticatedRequestContext,
    ) -> tuple[UUID, ...]:
        try:
            response = await self._client.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "apikey": self._publishable_key,
                    "Authorization": (
                        "Bearer "
                        f"{authenticated_request.access_token.get_secret_value()}"
                    ),
                },
                timeout=self._timeout,
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise CartServiceUnavailableError from None
        return _ids(response)

    async def profile_id(
        self, authenticated_request: AuthenticatedRequestContext
    ) -> UUID | None:
        # Filtered by the verified user id as well as by row-level security,
        # so an administrator's broader read cannot pick someone else's row.
        ids = await self._get(
            self._profiles,
            {
                "select": "id",
                "user_id": f"eq.{authenticated_request.user_id}",
                "limit": "2",
            },
            authenticated_request,
        )
        if len(ids) > 1:
            raise CartUpstreamError
        return ids[0] if ids else None

    async def cart_id(
        self,
        authenticated_request: AuthenticatedRequestContext,
        profile_id: UUID,
    ) -> UUID | None:
        ids = await self._get(
            self._carts,
            {
                "select": "id",
                "customer_profile_id": f"eq.{profile_id}",
                "limit": "2",
            },
            authenticated_request,
        )
        if len(ids) > 1:
            raise CartUpstreamError
        return ids[0] if ids else None


class SupabaseCartCreator:
    """The only holder of the secret key. One statement, one table."""

    def __init__(self, *, client: httpx.AsyncClient, settings: Settings) -> None:
        if settings.supabase_secret_key is None:
            raise ValueError("SupabaseCartCreator needs SUPABASE_SECRET_KEY")
        self._client = client
        self._carts = f"{str(settings.supabase_url).rstrip('/')}/rest/v1/cart"
        self._secret_key = settings.supabase_secret_key
        self._timeout = settings.supabase_auth_timeout_seconds

    def __repr__(self) -> str:
        return "SupabaseCartCreator(<secret key hidden>)"

    async def create(self, profile_id: UUID) -> UUID | None:
        try:
            response = await self._client.post(
                self._carts,
                params={"select": "id"},
                json={"customer_profile_id": str(profile_id)},
                headers={
                    "Accept": "application/json",
                    # A secret key in apikey alone makes the request run as
                    # service_role; it is not a JWT, so it is not sent as one.
                    "apikey": self._secret_key.get_secret_value(),
                    "Prefer": "return=representation",
                },
                timeout=self._timeout,
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise CartServiceUnavailableError from None
        # 409: cart_customer_unique. Another request created it first, which is
        # the outcome the caller wanted; the router reads it back as the user.
        if response.status_code == httpx.codes.CONFLICT:
            return None
        ids = _ids(response)
        if len(ids) != 1:
            raise CartUpstreamError
        return ids[0]
