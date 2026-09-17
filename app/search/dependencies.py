"""Dependency injection and safe errors for the search endpoint."""

from fastapi import HTTPException, Request, status

from app.ai.provider import AIProvider


def invalid_search_query(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "invalid_search_query", "message": message},
    )


def search_unavailable() -> HTTPException:
    """No provider configured, or the provider could not answer. Retryable."""

    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "search_unavailable",
            "message": "Search is temporarily unavailable.",
        },
    )


def search_upstream_error() -> HTTPException:
    """The provider answered with something that could not be trusted."""

    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "search_upstream_error",
            "message": "The search request could not be understood.",
        },
    )


async def get_ai_provider(request: Request) -> AIProvider:
    """Return the lifespan-owned provider, or refuse when AI is not configured.

    An instance with no provider key serves auth and catalogue normally and
    fails only here, which is the whole point of keeping the AI settings
    optional as a group.
    """

    provider = getattr(request.app.state, "ai_provider", None)
    if provider is None:
        raise search_unavailable()
    return provider
