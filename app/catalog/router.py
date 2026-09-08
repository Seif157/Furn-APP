"""Authenticated read-only catalogue endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

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
from app.catalog.models import ProductListResponse, ProductResponse
from app.catalog.transform import build_product_list_response, build_product_response

router = APIRouter(prefix="/v1/catalog", tags=["catalogue"])


@router.get("/products", response_model=ProductListResponse)
async def list_products(
    authenticated_request: Annotated[
        AuthenticatedRequestContext,
        Depends(get_authenticated_request),
    ],
    gateway: Annotated[CatalogueGateway, Depends(get_catalogue_gateway)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductListResponse:
    """Return one deterministic page of recommendation-eligible products."""

    try:
        products = await gateway.list_products(
            authenticated_request=authenticated_request,
            limit=limit,
            offset=offset,
        )
    except CatalogueServiceUnavailableError:
        raise catalogue_service_unavailable() from None
    except CatalogueUpstreamError:
        raise catalogue_upstream_error() from None

    return build_product_list_response(products, limit=limit, offset=offset)


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    authenticated_request: Annotated[
        AuthenticatedRequestContext,
        Depends(get_authenticated_request),
    ],
    gateway: Annotated[CatalogueGateway, Depends(get_catalogue_gateway)],
) -> ProductResponse:
    """Return one eligible product without revealing why other records are hidden."""

    try:
        product = await gateway.get_product(
            authenticated_request=authenticated_request,
            product_id=product_id,
        )
    except CatalogueServiceUnavailableError:
        raise catalogue_service_unavailable() from None
    except CatalogueUpstreamError:
        raise catalogue_upstream_error() from None

    if product is None:
        raise product_not_found()

    response = build_product_response(product)
    if response is None:
        raise product_not_found()
    return response
