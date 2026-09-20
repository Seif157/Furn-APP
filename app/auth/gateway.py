"""Asynchronous gateway for verifying access tokens with Supabase Auth."""

from typing import Protocol
from uuid import UUID

import httpx

from app.auth.models import AuthenticatedUser
from app.config import Settings


class InvalidAccessTokenError(Exception):
    """Raised when Supabase rejects a user access token."""


class AuthenticationServiceUnavailableError(Exception):
    """Raised when Supabase Auth cannot safely verify a token."""


class AuthenticationGateway(Protocol):
    """Interface used by the FastAPI authentication dependency."""

    async def authenticate(self, access_token: str) -> AuthenticatedUser:
        """Verify an access token and return its trusted user identity."""


class SupabaseAuthGateway:
    """Verify users through Supabase's server-side Auth endpoint."""

    def __init__(self, *, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._user_endpoint = f"{str(settings.supabase_url).rstrip('/')}/auth/v1/user"
        self._publishable_key = settings.supabase_publishable_key.get_secret_value()
        self._timeout_seconds = settings.supabase_auth_timeout_seconds

    async def authenticate(self, access_token: str) -> AuthenticatedUser:
        """Validate a bearer token without decoding or trusting local JWT claims."""

        try:
            response = await self._client.get(
                self._user_endpoint,
                headers={
                    "apikey": self._publishable_key,
                    "Authorization": f"Bearer {access_token}",
                },
                timeout=self._timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise AuthenticationServiceUnavailableError from None

        if response.status_code == httpx.codes.OK:
            return self._parse_user(response)

        if 400 <= response.status_code < 500 and response.status_code != 429:
            raise InvalidAccessTokenError

        raise AuthenticationServiceUnavailableError

    @staticmethod
    def _parse_user(response: httpx.Response) -> AuthenticatedUser:
        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise AuthenticationServiceUnavailableError from None

        if not isinstance(payload, dict):
            raise AuthenticationServiceUnavailableError

        raw_user_id = payload.get("id")
        if not isinstance(raw_user_id, str):
            raise AuthenticationServiceUnavailableError

        try:
            user_id = UUID(raw_user_id)
        except ValueError:
            raise AuthenticationServiceUnavailableError from None

        return AuthenticatedUser(user_id=user_id)
