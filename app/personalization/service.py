"""Build one customer's taste profile, cheaply and only when it can pay off.

Two upstream reads stand between a search and a profile: the customer's order
lines, and the products behind them. Doing that on every search would add two
round trips to a request that already makes three, so the result is cached per
user for the same fifteen minutes an identical search is cached, and a customer
with no purchase history costs one small read and then nothing.

Every failure is silent and ends in "no profile", which is exactly the
behaviour every customer had before this existed.
"""

from __future__ import annotations

from app.auth.models import AuthenticatedRequestContext
from app.catalog.gateway import (
    CatalogueGateway,
    CatalogueServiceUnavailableError,
    CatalogueUpstreamError,
)
from app.catalog.normalization import normalize_product
from app.core.cache import AICaches, cache_key
from app.personalization.gateway import PurchaseHistoryGateway
from app.personalization.profile import MIN_PURCHASES, TasteProfile, build_profile

MAX_LOOKUPS = 20
"""Distinct products to look up. The profile is a summary, not a history."""


async def taste_profile(
    *,
    authenticated_request: AuthenticatedRequestContext,
    history: PurchaseHistoryGateway | None,
    catalogue: CatalogueGateway,
    caches: AICaches | None = None,
) -> TasteProfile | None:
    """Return this caller's profile, or ``None`` when there is nothing to use."""

    if history is None:
        return None

    key = cache_key("taste", str(authenticated_request.user_id))
    if caches is not None:
        cached = caches.parses.get(key)
        if isinstance(cached, TasteProfile):
            return cached if cached.is_useful else None

    lines = await history.recent_lines(authenticated_request=authenticated_request)
    profile = TasteProfile()
    if len({line.product_id for line in lines}) >= MIN_PURCHASES:
        ordered_ids: list = []
        for line in lines:
            if line.product_id not in ordered_ids:
                ordered_ids.append(line.product_id)
        try:
            products = await catalogue.list_by_ids(
                authenticated_request=authenticated_request,
                product_ids=tuple(ordered_ids[:MAX_LOOKUPS]),
            )
        except (CatalogueServiceUnavailableError, CatalogueUpstreamError):
            products = ()
        profile = build_profile(
            tuple(normalize_product(product) for product in products),
            prices_paid=tuple(line.unit_price for line in lines),
        )

    if caches is not None:
        # Cached either way: knowing that someone has no history is worth the
        # same fifteen minutes as knowing what it is.
        caches.parses.put(key, profile)
    return profile if profile.is_useful else None
