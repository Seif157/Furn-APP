"""POST /v1/cart: make sure the signed-in customer has their one cart.

Call it before the first "add to cart". It is idempotent: the first call
creates the cart, every later call returns the same one. After that the app
adds, changes and removes cart lines in Supabase directly, as it does today.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth.dependencies import get_authenticated_request
from app.auth.models import AuthenticatedRequestContext
from app.cart.gateway import (
    CartCreator,
    CartServiceUnavailableError,
    CartUpstreamError,
    CustomerCartReader,
)
from app.catalog.models import StrictResponseModel

router = APIRouter(prefix="/v1", tags=["cart"])


class CartResponse(StrictResponseModel):
    cart_id: UUID
    created: bool
    """True only on the call that created it."""


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


def _unavailable() -> HTTPException:
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "cart_unavailable",
        "The cart is temporarily unavailable.",
    )


async def get_cart_reader(request: Request) -> CustomerCartReader:
    reader = getattr(request.app.state, "cart_reader", None)
    if reader is None:
        raise _unavailable()
    return reader


async def get_cart_creator(request: Request) -> CartCreator | None:
    """None when the server has no secret key; only creation then refuses."""

    return getattr(request.app.state, "cart_creator", None)


@router.post("/cart", response_model=CartResponse)
async def ensure_cart(
    authenticated_request: Annotated[
        AuthenticatedRequestContext, Depends(get_authenticated_request)
    ],
    reader: Annotated[CustomerCartReader, Depends(get_cart_reader)],
    creator: Annotated[CartCreator | None, Depends(get_cart_creator)],
) -> CartResponse:
    """Return the caller's cart, creating it the first time."""

    try:
        profile_id = await reader.profile_id(authenticated_request)
        if profile_id is None:
            # A seller or admin account, or a customer without a profile yet.
            raise _error(
                status.HTTP_409_CONFLICT,
                "customer_profile_required",
                "Only a customer account with a profile has a cart.",
            )

        existing = await reader.cart_id(authenticated_request, profile_id)
        if existing is not None:
            return CartResponse(cart_id=existing, created=False)

        if creator is None:
            raise _unavailable()
        created = await creator.create(profile_id)
        if created is not None:
            return CartResponse(cart_id=created, created=True)

        # Lost a race with a parallel call: the cart exists now. Read it back
        # as the user, so what is returned is what they are allowed to see.
        existing = await reader.cart_id(authenticated_request, profile_id)
        if existing is None:
            raise CartUpstreamError
        return CartResponse(cart_id=existing, created=False)
    except CartServiceUnavailableError:
        raise _unavailable() from None
    except CartUpstreamError:
        raise _error(
            status.HTTP_502_BAD_GATEWAY,
            "cart_upstream_error",
            "The cart could not be read or created.",
        ) from None
