"""GET /v1/reviews/public, the review reader Phase 3.2C requires.

After 3.2C, a signed-in customer can read only their own raw reviews, so a
Flutter screen that lists a product's reviews with the customer's own token
stops working. This endpoint is its replacement: it reads as the anonymous
role, which 3.2C allows to see the seven safe columns of reviews on products
that are for sale and on approved sellers.

No sign-in is required, because the same reviews are public to anyone
browsing. Nothing identifying the reviewer is ever returned.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.catalog.models import StrictResponseModel
from app.reviews.gateway import (
    ReviewGateway,
    ReviewServiceUnavailableError,
    ReviewUpstreamError,
)

router = APIRouter(prefix="/v1/reviews", tags=["reviews"])


class PublicReviewResponse(StrictResponseModel):
    id: UUID
    target_kind: str
    product_id: UUID | None
    seller_id: UUID | None
    rating: int
    comment: str | None
    created_at: datetime


class PublicReviewListResponse(StrictResponseModel):
    items: tuple[PublicReviewResponse, ...]
    limit: int
    offset: int
    has_more: bool


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


async def get_review_gateway(request: Request) -> ReviewGateway:
    try:
        return request.app.state.review_gateway
    except AttributeError:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "reviews_unavailable",
            "Reviews are temporarily unavailable.",
        ) from None


@router.get("/public", response_model=PublicReviewListResponse)
async def list_public_reviews(
    gateway: Annotated[ReviewGateway, Depends(get_review_gateway)],
    product_id: UUID | None = None,
    seller_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> PublicReviewListResponse:
    """Newest first. Exactly one of `product_id` or `seller_id` is required."""

    if (product_id is None) == (seller_id is None):
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_review_target",
            "Give exactly one of product_id or seller_id.",
        )
    target_kind = "product" if product_id is not None else "marketplace_party"
    target_id = product_id if product_id is not None else seller_id
    assert target_id is not None

    try:
        reviews = await gateway.list_public_reviews(
            target_kind=target_kind, target_id=target_id, limit=limit, offset=offset
        )
    except ReviewServiceUnavailableError:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "reviews_unavailable",
            "Reviews are temporarily unavailable.",
        ) from None
    except ReviewUpstreamError:
        raise _error(
            status.HTTP_502_BAD_GATEWAY,
            "reviews_upstream_error",
            "Reviews could not be read.",
        ) from None

    return PublicReviewListResponse(
        items=tuple(
            PublicReviewResponse(
                id=review.id,
                target_kind=review.target_kind,
                product_id=review.target_product_id,
                seller_id=review.target_marketplace_party_id,
                rating=review.rating,
                comment=review.comment,
                created_at=review.created_at,
            )
            for review in reviews[:limit]
        ),
        limit=limit,
        offset=offset,
        has_more=len(reviews) > limit,
    )
