"""Dependency injection for the intake endpoints."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.intake.gateway import ServiceDirectoryGateway


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "service_directory_unavailable",
            "message": "The service list could not be loaded.",
        },
    )


async def get_service_directory_gateway(request: Request) -> ServiceDirectoryGateway:
    """Return the lifespan-owned gateway, for replacement in tests."""

    try:
        return request.app.state.service_directory_gateway
    except AttributeError:
        raise _unavailable() from None
