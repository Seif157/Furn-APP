"""Read public reviews from PostgREST as the anonymous role.

This is the contract Phase 3.2C wrote down for any review reader: query as
anon, select exactly the seven columns anon is granted, and let row-level
security decide which rows come back. After 3.2C, a signed-in customer's own
token can read only their own reviews, so the public listing cannot use it.

Only the publishable key is sent, with no user token, so the request runs as
anon. Nothing here ever names `customer_profile_id` or
`target_service_request_id`: after 3.2C anon has no grant on either, and even
filtering on one would be refused.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from app.config import Settings

PUBLIC_REVIEW_COLUMNS = (
    "id,target_kind,target_product_id,target_marketplace_party_id,"
    "rating,comment,created_at"
)

TargetKind = Literal["product", "marketplace_party"]


class UpstreamReview(BaseModel):
    # Not strict: timestamps arrive from JSON as strings.
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    target_kind: str
    target_product_id: UUID | None
    target_marketplace_party_id: UUID | None
    rating: int
    comment: str | None
    created_at: datetime


_REVIEWS = TypeAdapter(tuple[UpstreamReview, ...])


class ReviewServiceUnavailableError(Exception):
    pass


class ReviewUpstreamError(Exception):
    pass


class ReviewGateway(Protocol):
    async def list_public_reviews(
        self, *, target_kind: TargetKind, target_id: UUID, limit: int, offset: int
    ) -> tuple[UpstreamReview, ...]: ...


class SupabaseReviewGateway:
    def __init__(self, *, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._endpoint = f"{str(settings.supabase_url).rstrip('/')}/rest/v1/review"
        self._publishable_key = settings.supabase_publishable_key.get_secret_value()
        self._timeout_seconds = settings.supabase_auth_timeout_seconds

    async def list_public_reviews(
        self, *, target_kind: TargetKind, target_id: UUID, limit: int, offset: int
    ) -> tuple[UpstreamReview, ...]:
        target_column = (
            "target_product_id"
            if target_kind == "product"
            else "target_marketplace_party_id"
        )
        params = {
            "select": PUBLIC_REVIEW_COLUMNS,
            "target_kind": f"eq.{target_kind}",
            target_column: f"eq.{target_id}",
            "order": "created_at.desc,id.asc",
            # One past the page, to report whether there is another.
            "limit": str(limit + 1),
            "offset": str(offset),
        }
        try:
            response = await self._client.get(
                self._endpoint,
                params=params,
                # The publishable key alone makes this an anonymous request.
                headers={"Accept": "application/json", "apikey": self._publishable_key},
                timeout=self._timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise ReviewServiceUnavailableError from None

        if response.status_code >= 500 or response.status_code == 429:
            raise ReviewServiceUnavailableError
        if response.status_code != httpx.codes.OK:
            raise ReviewUpstreamError
        try:
            reviews = _REVIEWS.validate_json(response.content)
        except ValidationError:
            raise ReviewUpstreamError from None

        # Rechecked here as well as filtered upstream: a row for another target
        # or with conflicting targets is dropped, never shown.
        return tuple(
            review
            for review in reviews
            if review.target_kind == target_kind
            and (
                review.target_product_id == target_id
                and review.target_marketplace_party_id is None
                if target_kind == "product"
                else review.target_marketplace_party_id == target_id
                and review.target_product_id is None
            )
        )
