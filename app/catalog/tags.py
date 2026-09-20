"""Read platform-inferred search tags (style, room type, feel).

These are guesses, not catalogue facts, so they live in their own table rather
than in the seller's enrichment rows: a 3.2B restrictive policy deliberately
hides unconfirmed enrichment from customers, and quietly writing guesses into
a seller-confirmed shape would work around a reviewed security decision instead
of respecting it.

The read is separate from the catalogue query and fails soft. Two reasons. The
catalogue must not break because a tag table is missing, unreachable, or empty,
which is exactly the state before the migration is applied. And a missing tag
costs ranking quality only: every hard constraint has already been decided from
real catalogue data by the time these are used.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.auth.models import AuthenticatedRequestContext
from app.catalog.normalization import (
    TAG_VOCABULARIES,
    InferredTag,
    NormalizedProduct,
    with_tags,
)
from app.config import Settings
from app.search.models import SearchSpecification

TAG_SELECT = "product_id,tag_kind,tag_slug,confidence"
MAX_TAGS_PER_REQUEST = 600
"""A page of 50 products with a dozen tags each, with room to spare."""


class SearchTagGateway(Protocol):
    """Interface consumed by the search and room routes."""

    async def tags_for(
        self,
        *,
        authenticated_request: AuthenticatedRequestContext,
        product_ids: tuple[UUID, ...],
    ) -> dict[UUID, tuple[InferredTag, ...]]:
        """Return inferred tags per product; an empty mapping is always valid."""


def parse_tag_rows(rows: object) -> dict[UUID, tuple[InferredTag, ...]]:
    """Turn untrusted PostgREST rows into validated tags, dropping the rest.

    A row is dropped, never repaired: an unknown slug or a confidence outside
    (0, 1] means the tag table disagrees with this build's vocabulary, and a
    guess is not worth widening the vocabulary at request time.
    """

    collected: dict[UUID, list[InferredTag]] = defaultdict(list)
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = row.get("tag_kind")
        slug = row.get("tag_slug")
        if kind not in TAG_VOCABULARIES or not isinstance(slug, str):
            continue
        try:
            product_id = UUID(str(row.get("product_id")))
            confidence = Decimal(str(row.get("confidence")))
            tag = InferredTag(kind=kind, slug=slug, confidence=confidence)
        except (ValueError, ArithmeticError, InvalidOperation, ValidationError):
            continue
        collected[product_id].append(tag)
    return {product_id: tuple(tags) for product_id, tags in collected.items() if tags}


class SupabaseSearchTagGateway:
    """Fetch inferred tags for a page of products with the caller's own token."""

    def __init__(self, *, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._endpoint = (
            f"{str(settings.supabase_url).rstrip('/')}/rest/v1/product_search_tag"
        )
        self._publishable_key = settings.supabase_publishable_key.get_secret_value()
        self._timeout_seconds = settings.supabase_auth_timeout_seconds

    async def tags_for(
        self,
        *,
        authenticated_request: AuthenticatedRequestContext,
        product_ids: tuple[UUID, ...],
    ) -> dict[UUID, tuple[InferredTag, ...]]:
        if not product_ids:
            return {}
        identifiers = ",".join(str(product_id) for product_id in product_ids)
        try:
            response = await self._client.get(
                self._endpoint,
                params={
                    "select": TAG_SELECT,
                    "product_id": f"in.({identifiers})",
                    "limit": str(MAX_TAGS_PER_REQUEST),
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
            return {}
        if response.status_code != httpx.codes.OK:
            # Includes the 404 every request returns before the migration is
            # applied. Ranking simply loses a signal it never had.
            return {}
        try:
            return parse_tag_rows(response.json())
        except ValueError:
            return {}


def wants_inferred_tags(specification: SearchSpecification) -> bool:
    """True when the sentence asked for something only a tag can answer."""

    soft = specification.soft
    return bool(soft.styles or soft.feels or soft.room_type is not None)


async def attach_inferred_tags(
    products: tuple[NormalizedProduct, ...],
    *,
    gateway: SearchTagGateway | None,
    authenticated_request: AuthenticatedRequestContext,
    specification: SearchSpecification,
) -> tuple[NormalizedProduct, ...]:
    """Attach tags to the candidates, or return them untouched.

    Nothing is fetched for a sentence that mentions no style, room, or feel,
    so the common search costs exactly the requests it did before.
    """

    if gateway is None or not products or not wants_inferred_tags(specification):
        return products
    tags = await gateway.tags_for(
        authenticated_request=authenticated_request,
        product_ids=tuple(product.id for product in products),
    )
    if not tags:
        return products
    return tuple(
        with_tags(product, tags[product.id]) if product.id in tags else product
        for product in products
    )
