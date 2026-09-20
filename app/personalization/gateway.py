"""Read the caller's own order lines, with the caller's own token.

Row-level security is what makes this safe, and it is also what makes it
limited: a seller reading this table sees the orders sent to them, not orders
they placed. The gateway therefore restricts the read to lines whose order
belongs to this user's customer profile, and returns nothing at all when that
cannot be established. A profile built from someone else's purchases would be
both wrong and a small privacy failure, so it is refused rather than
approximated.

Failing soft is the rule here as with inferred tags: personalization only ever
breaks ties, so an unavailable history costs nothing that matters.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict

from app.auth.models import AuthenticatedRequestContext
from app.config import Settings

MAX_LINES = 60
"""Enough history to see a pattern; bounded so one request stays small."""

HISTORY_SELECT = (
    "product_id,unit_price,"
    "purchase_order!inner(customer_profile_id,"
    "customer_profile!inner(user_id))"
)


class PurchasedLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    product_id: UUID
    unit_price: Decimal


class PurchaseHistoryGateway(Protocol):
    async def recent_lines(
        self, *, authenticated_request: AuthenticatedRequestContext
    ) -> tuple[PurchasedLine, ...]:
        """Return this customer's own recent order lines, or nothing."""


def parse_history_rows(rows: object) -> tuple[PurchasedLine, ...]:
    """Validate untrusted rows, dropping anything that is not a bought product."""

    if not isinstance(rows, list):
        return ()
    lines: list[PurchasedLine] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            product_id = UUID(str(row.get("product_id")))
            unit_price = Decimal(str(row.get("unit_price")))
        except (ValueError, TypeError, ArithmeticError, InvalidOperation):
            continue
        if not unit_price.is_finite() or unit_price < 0:
            continue
        lines.append(PurchasedLine(product_id=product_id, unit_price=unit_price))
    return tuple(lines)


class SupabasePurchaseHistoryGateway:
    """Fetch the caller's own purchased lines through PostgREST."""

    def __init__(self, *, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._endpoint = (
            f"{str(settings.supabase_url).rstrip('/')}/rest/v1/order_line_item"
        )
        self._publishable_key = settings.supabase_publishable_key.get_secret_value()
        self._timeout_seconds = settings.supabase_auth_timeout_seconds

    async def recent_lines(
        self, *, authenticated_request: AuthenticatedRequestContext
    ) -> tuple[PurchasedLine, ...]:
        try:
            response = await self._client.get(
                self._endpoint,
                params={
                    "select": HISTORY_SELECT,
                    # The identity comes from the verified token, never from
                    # anything the client sent.
                    "purchase_order.customer_profile.user_id": (
                        f"eq.{authenticated_request.user_id}"
                    ),
                    "limit": str(MAX_LINES),
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
            return parse_history_rows(response.json())
        except ValueError:
            return ()
