"""Comparison and similar-product endpoints (Phase 6D).

POST /v1/compare                               2 to 4 products side by side
GET  /v1/catalog/products/{product_id}/similar real products like this one

Neither calls a model, so neither is rate limited or cached. Both read the
catalogue with the caller's own token through the existing gateway, so
row-level security decides what can be compared or suggested, and every
product is rechecked for eligibility exactly as the catalogue endpoints do.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.dependencies import get_authenticated_request
from app.auth.models import AuthenticatedRequestContext
from app.catalog.dependencies import (
    catalogue_service_unavailable,
    catalogue_upstream_error,
    get_catalogue_gateway,
    product_not_found,
)
from app.catalog.gateway import (
    CatalogueGateway,
    CatalogueServiceUnavailableError,
    CatalogueUpstreamError,
)
from app.catalog.models import ProductResponse, StrictResponseModel
from app.catalog.normalization import normalize_product
from app.catalog.transform import build_product_response, is_recommendation_eligible
from app.recommendations.comparison import (
    MAX_COMPARED,
    MIN_COMPARED,
    ComparisonResponse,
    build_comparison,
)
from app.recommendations.models import ReasonResponse
from app.recommendations.similar import (
    DEFAULT_SIMILAR,
    MAX_SIMILAR,
    find_similar,
    similar_reasons,
)
from app.search.router import CANDIDATE_LIMIT

router = APIRouter(prefix="/v1", tags=["recommendations"])


class CompareRequest(BaseModel):
    # Not strict, like the room image request: ids arrive from JSON as strings.
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_ids: Annotated[
        list[UUID], Field(min_length=MIN_COMPARED, max_length=MAX_COMPARED)
    ]
    language: Literal["ar", "en"] = "en"

    @field_validator("product_ids")
    @classmethod
    def distinct(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("product_ids must be distinct")
        return value


class SimilarItemResponse(StrictResponseModel):
    product: ProductResponse
    price_difference: Decimal
    """Signed, as a decimal string: negative means cheaper than this product."""
    reasons: tuple[ReasonResponse, ...]


class SimilarResponse(StrictResponseModel):
    product_id: UUID
    language: str
    items: tuple[SimilarItemResponse, ...]
    candidate_count: int
    truncated: bool


async def _one_product(
    gateway: CatalogueGateway,
    authenticated_request: AuthenticatedRequestContext,
    product_id: UUID,
):
    try:
        product = await gateway.get_product(
            authenticated_request=authenticated_request, product_id=product_id
        )
    except CatalogueServiceUnavailableError:
        raise catalogue_service_unavailable() from None
    except CatalogueUpstreamError:
        raise catalogue_upstream_error() from None
    shown = build_product_response(product) if product is not None else None
    if product is None or shown is None:
        raise product_not_found()
    return product, shown


@router.post("/compare", response_model=ComparisonResponse)
async def compare(
    compare_request: CompareRequest,
    authenticated_request: Annotated[
        AuthenticatedRequestContext, Depends(get_authenticated_request)
    ],
    gateway: Annotated[CatalogueGateway, Depends(get_catalogue_gateway)],
) -> ComparisonResponse:
    """Compare real products the caller may see, in the order they were sent."""

    fetched = [
        await _one_product(gateway, authenticated_request, product_id)
        for product_id in compare_request.product_ids
    ]
    return build_comparison(
        [normalize_product(product) for product, _ in fetched],
        [shown for _, shown in fetched],
        {shown.id: shown.seller.business_name for _, shown in fetched},
        compare_request.language,
    )


@router.get("/catalog/products/{product_id}/similar", response_model=SimilarResponse)
async def similar(
    product_id: UUID,
    authenticated_request: Annotated[
        AuthenticatedRequestContext, Depends(get_authenticated_request)
    ],
    gateway: Annotated[CatalogueGateway, Depends(get_catalogue_gateway)],
    limit: Annotated[int, Query(ge=1, le=MAX_SIMILAR)] = DEFAULT_SIMILAR,
    language: Literal["ar", "en"] = "en",
) -> SimilarResponse:
    """Suggest real products of the same kind that share facts with this one."""

    product, _ = await _one_product(gateway, authenticated_request, product_id)

    try:
        products = await gateway.list_products(
            authenticated_request=authenticated_request,
            limit=CANDIDATE_LIMIT,
            offset=0,
        )
    except CatalogueServiceUnavailableError:
        raise catalogue_service_unavailable() from None
    except CatalogueUpstreamError:
        raise catalogue_upstream_error() from None

    truncated = len(products) > CANDIDATE_LIMIT
    eligible = {
        candidate.id: candidate
        for candidate in products[:CANDIDATE_LIMIT]
        if is_recommendation_eligible(candidate)
    }
    found = find_similar(
        normalize_product(product),
        (normalize_product(candidate) for candidate in eligible.values()),
        limit=limit,
    )

    items: list[SimilarItemResponse] = []
    for item in found:
        shown = build_product_response(eligible[item.product.id])
        if shown is None:
            continue
        items.append(
            SimilarItemResponse(
                product=shown,
                price_difference=item.price_difference,
                reasons=similar_reasons(item, language),
            )
        )
    return SimilarResponse(
        product_id=product_id,
        language=language,
        items=tuple(items),
        candidate_count=len(eligible),
        truncated=truncated,
    )
