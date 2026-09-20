"""Dependency injection and safe errors for catalogue access."""

from fastapi import HTTPException, Request, status

from app.catalog.gateway import CatalogueGateway
from app.catalog.tags import SearchTagGateway
from app.personalization.gateway import PurchaseHistoryGateway
from app.recommendations.offerings import OfferingGateway


def catalogue_upstream_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "catalogue_upstream_error",
            "message": "The catalogue could not be loaded.",
        },
    )


def catalogue_service_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "catalogue_service_unavailable",
            "message": "The catalogue is temporarily unavailable.",
        },
    )


def product_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "product_not_found",
            "message": "The product was not found.",
        },
    )


async def get_search_tag_gateway(request: Request) -> SearchTagGateway | None:
    """Return the lifespan-owned tag gateway, or ``None`` when unavailable.

    Absence is not an error here, unlike the catalogue: inferred tags rank
    results, they never decide which products exist.
    """

    return getattr(request.app.state, "search_tag_gateway", None)


async def get_purchase_history_gateway(
    request: Request,
) -> PurchaseHistoryGateway | None:
    """Return the lifespan-owned history gateway, or ``None``.

    Absent, searches are simply not personalized, which is what every search
    did before Phase 9B.
    """

    return getattr(request.app.state, "purchase_history_gateway", None)


async def get_offering_gateway(request: Request) -> OfferingGateway | None:
    """Return the lifespan-owned offering gateway, or ``None``."""

    return getattr(request.app.state, "offering_gateway", None)


async def get_catalogue_gateway(request: Request) -> CatalogueGateway:
    """Return the lifespan-owned gateway for replacement in deterministic tests."""

    try:
        return request.app.state.catalogue_gateway
    except AttributeError:
        raise catalogue_service_unavailable() from None
