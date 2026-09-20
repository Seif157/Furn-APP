"""When the catalogue has nothing, offer the sellers who make things to order.

Section 6.10: when no exact match exists, show nearest real alternatives and,
optionally, a clearly-labelled seller result. Nearest alternatives already
exist (app/recommendations/alternatives.py). This adds the second half, and
keeps it honest in three ways.

It is never a product. A custom offering is a seller's published offer to make
something; it has no stock, no colour and no delivery promise, so it is
returned in its own list, never mixed into results, and carries a label saying
what it is.

It appears only when nothing matched. A labelled seller offer next to real
matches would be an advertisement competing with an answer.

Nothing is sponsored. This marketplace has no paid placement, and inventing a
"sponsored" flag for something nobody paid for would be the disguise section
6.10 forbids. If paid placement is ever added, it belongs here, labelled, and
never in the ranked results.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict

from app.auth.models import AuthenticatedRequestContext
from app.config import Settings

MAX_OFFERS = 3
OFFERING_SELECT = "id,title,description,published_price,marketplace_party_id"

LABELS: dict[Literal["ar", "en"], str] = {
    "en": "Made to order by a seller, not a catalogue product",
    "ar": "تصنيع حسب الطلب من أحد التجار، مش منتج من الكتالوج",
}


class SellerOffering(BaseModel):
    """One published, made-to-order offering."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    title: str
    description: str | None
    price: Decimal | None
    """The seller's published price, when they published one."""
    seller_id: UUID


class OfferingGateway(Protocol):
    async def published(
        self, *, authenticated_request: AuthenticatedRequestContext
    ) -> tuple[SellerOffering, ...]:
        """Return published offerings, newest first, or nothing."""


def parse_offering_rows(rows: object) -> tuple[SellerOffering, ...]:
    """Validate untrusted rows, dropping anything that cannot be shown."""

    if not isinstance(rows, list):
        return ()
    offerings: list[SellerOffering] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        try:
            identifier = UUID(str(row.get("id")))
            seller_id = UUID(str(row.get("marketplace_party_id")))
        except (ValueError, TypeError):
            continue
        price: Decimal | None
        raw_price = row.get("published_price")
        if raw_price is None:
            price = None
        else:
            try:
                price = Decimal(str(raw_price))
            except (ArithmeticError, InvalidOperation, ValueError):
                continue
            if not price.is_finite() or price < 0:
                continue
        description = row.get("description")
        offerings.append(
            SellerOffering(
                id=identifier,
                title=title.strip(),
                description=(
                    description.strip()
                    if isinstance(description, str) and description.strip()
                    else None
                ),
                price=price,
                seller_id=seller_id,
            )
        )
    return tuple(offerings)


class SupabaseOfferingGateway:
    """Read published custom offerings with the caller's own token."""

    def __init__(self, *, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._endpoint = (
            f"{str(settings.supabase_url).rstrip('/')}/rest/v1/custom_offering"
        )
        self._publishable_key = settings.supabase_publishable_key.get_secret_value()
        self._timeout_seconds = settings.supabase_auth_timeout_seconds

    async def published(
        self, *, authenticated_request: AuthenticatedRequestContext
    ) -> tuple[SellerOffering, ...]:
        try:
            response = await self._client.get(
                self._endpoint,
                params={
                    "select": OFFERING_SELECT,
                    "publication_state": "eq.published",
                    "order": "published_at.desc",
                    "limit": str(MAX_OFFERS),
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
            return parse_offering_rows(response.json())
        except ValueError:
            return ()
