"""Dependency injection and safe, localized errors for the search endpoint.

Error messages answer in the customer's language for the same reason results
do. The machine-readable `code` never changes with language, so a client can
branch on it and still show the localized `message`.
"""

from fastapi import HTTPException, Request, status

from app.ai.provider import AIProvider
from app.search.localization import MessageCode, message
from app.search.models import Language


def invalid_search_query(code: MessageCode, language: Language) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "invalid_search_query",
            "message": message(code, language),
        },
    )


def search_unavailable(language: Language) -> HTTPException:
    """No provider configured, or the provider could not answer. Retryable."""

    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "search_unavailable",
            "message": message("search_unavailable", language),
        },
    )


def search_upstream_error(language: Language) -> HTTPException:
    """The provider answered with something that could not be trusted."""

    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "search_upstream_error",
            "message": message("search_upstream_error", language),
        },
    )


async def get_optional_ai_provider(request: Request) -> AIProvider | None:
    """Return the lifespan-owned provider, or ``None`` when AI is not configured.

    The absence is reported by the route rather than raised here, because only
    the route knows which language to refuse in. An instance with no provider
    key serves auth and catalogue normally and fails only on search, which is
    the whole point of keeping the AI settings optional as a group.
    """

    return getattr(request.app.state, "ai_provider", None)
