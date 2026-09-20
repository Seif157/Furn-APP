"""Help a customer fill in a request the marketplace can act on.

Two endpoints, one idea: the app already has a service-request form and a
furnishing-request form, and both ask a customer to translate their own problem
into the marketplace's categories. These read one sentence and fill the form in.

Neither writes anything. The app still creates the row in Supabase under the
customer's own row-level security, exactly as documented for Flutter, so this
is advice about a form and never an action taken on someone's behalf.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.ai.provider import (
    AIProvider,
    AIProviderError,
    AIProviderUnavailableError,
)
from app.ai.service import MAX_HISTORY, InvalidQueryError
from app.auth.dependencies import get_authenticated_request
from app.auth.models import AuthenticatedRequestContext
from app.catalog.normalization import FEELS, ROOM_TYPES, STYLES
from app.core.cache import cache_key, get_ai_caches
from app.core.limits import enforce_rate_limit
from app.intake.brief import read_brief
from app.intake.dependencies import get_service_directory_gateway
from app.intake.gateway import ServiceDirectoryGateway
from app.intake.models import (
    BriefResponse,
    BriefRoomResponse,
    ServiceMatchResponse,
    ServiceTriageResponse,
)
from app.intake.triage import triage_request
from app.search.dependencies import (
    get_optional_ai_provider,
    invalid_search_query,
    search_unavailable,
    search_upstream_error,
)
from app.search.localization import response_language, term_label
from app.search.models import MAX_TEXT_LENGTH, detect_language
from app.search.responses import TermResponse, UnresolvedResponse

router = APIRouter(prefix="/v1/intake", tags=["intake"])

SERVICE_DIRECTORY_UNAVAILABLE = {
    "en": "The service list could not be loaded.",
    "ar": "تعذّر تحميل قائمة الخدمات. برجاء المحاولة بعد قليل.",
}


class IntakeRequest(BaseModel):
    """One description, bounded before a provider call is spent."""

    model_config = ConfigDict(extra="forbid", strict=True)

    description: Annotated[str, Field(min_length=1, max_length=MAX_TEXT_LENGTH)]
    history: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=MAX_TEXT_LENGTH)]],
        Field(max_length=MAX_HISTORY),
    ] = []


def service_directory_unavailable(language: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "service_directory_unavailable",
            "message": SERVICE_DIRECTORY_UNAVAILABLE[language],
        },
    )


@router.post("/service", response_model=ServiceTriageResponse)
async def classify_service_request(
    request: Request,
    intake_request: IntakeRequest,
    authenticated_request: Annotated[
        AuthenticatedRequestContext, Depends(get_authenticated_request)
    ],
    directory: Annotated[
        ServiceDirectoryGateway, Depends(get_service_directory_gateway)
    ],
    provider: Annotated[AIProvider | None, Depends(get_optional_ai_provider)],
) -> ServiceTriageResponse:
    """Match a described problem to the services the marketplace really offers."""

    language = detect_language(
        " ".join([*intake_request.history, intake_request.description])
    )
    spoken = response_language(language)
    if provider is None:
        raise search_unavailable(language)
    enforce_rate_limit(
        request,
        user_id=authenticated_request.user_id,
        bucket="intake",
        language=language,
    )

    services = await directory.list_active(authenticated_request=authenticated_request)
    if not services:
        # Either the directory is unreachable or this account may not read it.
        # Guessing a service would be worse than saying so.
        raise service_directory_unavailable(spoken)

    caches = get_ai_caches(request)
    key = cache_key(
        "intake_service",
        ",".join(str(service.id) for service in services),
        str(len(intake_request.history)),
        *intake_request.history,
        intake_request.description,
    )
    cached = caches.parses.get(key) if caches is not None else None
    try:
        if isinstance(cached, ServiceTriageResponse):
            return cached
        triage = await triage_request(
            intake_request.description,
            services=services,
            provider=provider,
            history=intake_request.history,
        )
    except InvalidQueryError:
        raise invalid_search_query("query_empty", language) from None
    except AIProviderUnavailableError:
        raise search_unavailable(language) from None
    except AIProviderError:
        raise search_upstream_error(language) from None

    response = ServiceTriageResponse(
        language=spoken,
        services=tuple(
            ServiceMatchResponse(
                id=match.service.id,
                name=match.service.name,
                description=match.service.description,
                confidence=match.confidence,
            )
            for match in triage.services
        ),
        clarification=triage.clarification,
    )
    if caches is not None:
        caches.parses.put(key, response)
    return response


@router.post("/furnishing", response_model=BriefResponse)
async def read_furnishing_brief(
    request: Request,
    intake_request: IntakeRequest,
    authenticated_request: Annotated[
        AuthenticatedRequestContext, Depends(get_authenticated_request)
    ],
    provider: Annotated[AIProvider | None, Depends(get_optional_ai_provider)],
) -> BriefResponse:
    """Read a furnishing job into the fields the request form already has."""

    language = detect_language(
        " ".join([*intake_request.history, intake_request.description])
    )
    spoken = response_language(language)
    if provider is None:
        raise search_unavailable(language)
    enforce_rate_limit(
        request,
        user_id=authenticated_request.user_id,
        bucket="intake",
        language=language,
    )

    caches = get_ai_caches(request)
    key = cache_key(
        "intake_furnishing",
        str(len(intake_request.history)),
        *intake_request.history,
        intake_request.description,
    )
    cached = caches.parses.get(key) if caches is not None else None
    try:
        if isinstance(cached, BriefResponse):
            return cached
        brief = await read_brief(
            intake_request.description,
            provider=provider,
            history=intake_request.history,
        )
    except InvalidQueryError:
        raise invalid_search_query("query_empty", language) from None
    except AIProviderUnavailableError:
        raise search_unavailable(language) from None
    except AIProviderError:
        raise search_upstream_error(language) from None

    response = BriefResponse(
        language=spoken,
        rooms=tuple(
            BriefRoomResponse(
                room_type=TermResponse(
                    slug=room.room_type,
                    label=term_label(ROOM_TYPES, room.room_type, language),
                ),
                quantity=room.quantity,
            )
            for room in brief.rooms
        ),
        total_budget=brief.total_budget,
        styles=tuple(
            TermResponse(slug=slug, label=term_label(STYLES, slug, language))
            for slug in brief.styles
        ),
        feels=tuple(
            TermResponse(slug=slug, label=term_label(FEELS, slug, language))
            for slug in brief.feels
        ),
        unresolved=tuple(
            UnresolvedResponse(field=term.field, surface=term.surface)
            for term in brief.unresolved
        ),
        clarification=brief.clarification,
    )
    if caches is not None:
        caches.parses.put(key, response)
    return response
