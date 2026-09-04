"""FastAPI dependencies enforcing Supabase authentication."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from app.auth.gateway import (
    AuthenticationGateway,
    AuthenticationServiceUnavailableError,
    InvalidAccessTokenError,
)
from app.auth.models import AuthenticatedUser


def _authentication_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "authentication_required",
            "message": "Authentication is required.",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def _invalid_access_token() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "invalid_access_token",
            "message": "The access token is invalid or expired.",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def _authentication_service_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "authentication_service_unavailable",
            "message": "Authentication is temporarily unavailable.",
        },
    )


async def get_bearer_token(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> str:
    """Extract one non-empty bearer token from the Authorization header."""

    if authorization is None:
        raise _authentication_required()

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise _authentication_required()

    return parts[1]


async def get_auth_gateway(request: Request) -> AuthenticationGateway:
    """Return the application-owned gateway for dependency injection."""

    try:
        return request.app.state.auth_gateway
    except AttributeError:
        raise _authentication_service_unavailable() from None


async def get_current_user(
    access_token: Annotated[str, Depends(get_bearer_token)],
    gateway: Annotated[AuthenticationGateway, Depends(get_auth_gateway)],
) -> AuthenticatedUser:
    """Return the user identity only after Supabase verifies the access token."""

    try:
        return await gateway.authenticate(access_token)
    except InvalidAccessTokenError:
        raise _invalid_access_token() from None
    except AuthenticationServiceUnavailableError:
        raise _authentication_service_unavailable() from None
