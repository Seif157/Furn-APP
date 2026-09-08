"""Dependency injection and safe errors for catalogue access."""

from fastapi import HTTPException, Request, status

from app.catalog.gateway import CatalogueGateway


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


async def get_catalogue_gateway(request: Request) -> CatalogueGateway:
    """Return the lifespan-owned gateway for replacement in deterministic tests."""

    try:
        return request.app.state.catalogue_gateway
    except AttributeError:
        raise catalogue_service_unavailable() from None
