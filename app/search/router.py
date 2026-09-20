"""Authenticated natural-language search over the real catalogue (Phase 5C).

One sentence in, ranked real products out. The endpoint is the join between
three pieces that already existed and were tested separately: the Phase 5A
parser, the Phase 4B normalizer, and the Phase 4D deterministic search.

Two properties are worth stating because they are easy to lose later.

The catalogue is read with the caller's own token, through the same gateway
the catalogue endpoints use, so row-level security decides what can be
searched. Search cannot widen what a user may see.

Retrieval is deterministic. The model shapes the question; it never touches
the answer. Ranking, filtering, and ordering are the same code a hand-built
specification runs through, so two identical sentences return the same page.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.ai.models import ParsedRequirements
from app.ai.provider import (
    AIProvider,
    AIProviderError,
    AIProviderUnavailableError,
)
from app.ai.service import MAX_HISTORY, InvalidQueryError, parse_requirements
from app.auth.dependencies import get_authenticated_request
from app.auth.models import AuthenticatedRequestContext
from app.catalog.dependencies import (
    catalogue_service_unavailable,
    catalogue_upstream_error,
    get_catalogue_gateway,
    get_offering_gateway,
    get_purchase_history_gateway,
    get_search_tag_gateway,
)
from app.catalog.gateway import (
    CatalogueGateway,
    CatalogueServiceUnavailableError,
    CatalogueUpstreamError,
)
from app.catalog.normalization import normalize_product
from app.catalog.tags import SearchTagGateway, attach_inferred_tags
from app.catalog.transform import is_recommendation_eligible
from app.core.cache import cache_key, get_ai_caches
from app.core.limits import enforce_rate_limit
from app.personalization.gateway import PurchaseHistoryGateway
from app.personalization.service import taste_profile
from app.recommendations.alternatives import nearest_alternatives
from app.recommendations.offerings import OfferingGateway
from app.search.dependencies import (
    get_optional_ai_provider,
    invalid_search_query,
    search_unavailable,
    search_upstream_error,
)
from app.search.models import (
    DEFAULT_RESULTS,
    MAX_RESULTS,
    MAX_TEXT_LENGTH,
    detect_language,
)
from app.search.responses import SearchResponse, build_search_response
from app.search.service import search_products

CANDIDATE_LIMIT = 200
"""How many eligible products one search examines.

Retrieval is in-memory, so this bounds the work a single request can cause.
Beyond it the response reports `truncated`, because a silently shortened
candidate set would produce confidently wrong results. Raising this past a few
hundred is the signal to push filtering into the database instead.
"""

router = APIRouter(prefix="/v1/search", tags=["search"])


class SearchRequest(BaseModel):
    """The only user-controlled input, bounded before a provider call is spent."""

    model_config = ConfigDict(extra="forbid", strict=True)

    query: Annotated[str, Field(min_length=1, max_length=MAX_TEXT_LENGTH)]
    limit: Annotated[int, Field(ge=1, le=MAX_RESULTS)] = DEFAULT_RESULTS
    history: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=MAX_TEXT_LENGTH)]],
        Field(max_length=MAX_HISTORY),
    ] = []
    """The customer's earlier messages in this conversation, oldest first.
    With history, "in grey instead" refines the earlier search rather than
    starting over. The app keeps the list; the server keeps nothing."""


@router.post("", response_model=SearchResponse)
async def search(
    request: Request,
    search_request: SearchRequest,
    authenticated_request: Annotated[
        AuthenticatedRequestContext,
        Depends(get_authenticated_request),
    ],
    gateway: Annotated[CatalogueGateway, Depends(get_catalogue_gateway)],
    tag_gateway: Annotated[SearchTagGateway | None, Depends(get_search_tag_gateway)],
    history_gateway: Annotated[
        PurchaseHistoryGateway | None, Depends(get_purchase_history_gateway)
    ],
    offering_gateway: Annotated[OfferingGateway | None, Depends(get_offering_gateway)],
    provider: Annotated[AIProvider | None, Depends(get_optional_ai_provider)],
) -> SearchResponse:
    """Parse one sentence, then rank the products the caller is allowed to see."""

    # Detected from the raw sentence rather than from the parsed specification,
    # so a failure before or during parsing can still be reported in the
    # customer's own language.
    language = detect_language(
        " ".join([*search_request.history, search_request.query])
    )
    if provider is None:
        raise search_unavailable(language)
    enforce_rate_limit(
        request,
        user_id=authenticated_request.user_id,
        bucket="search",
        language=language,
    )

    caches = get_ai_caches(request)
    key = cache_key(
        "search",
        str(search_request.limit),
        str(len(search_request.history)),
        *search_request.history,
        search_request.query,
    )
    try:
        cached = caches.parses.get(key) if caches is not None else None
        if isinstance(cached, ParsedRequirements):
            parsed = cached
        else:
            parsed = await parse_requirements(
                search_request.query,
                provider=provider,
                limit=search_request.limit,
                history=search_request.history,
            )
            if caches is not None:
                caches.parses.put(key, parsed)
    except InvalidQueryError:
        raise invalid_search_query("query_empty", language) from None
    except AIProviderUnavailableError:
        raise search_unavailable(language) from None
    except AIProviderError:
        # Everything else from the boundary is an untrustworthy answer. The
        # errors carry no prompt and no response body, so nothing is lost by
        # collapsing them here.
        raise search_upstream_error(language) from None

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

    # The gateway fetches one product beyond the page to detect a next page.
    # Here that extra row is only evidence that the catalogue outgrew one
    # search, so it is reported and not searched.
    truncated = len(products) > CANDIDATE_LIMIT
    candidates = tuple(
        product
        for product in products[:CANDIDATE_LIMIT]
        # Eligibility is rechecked independently of the gateway's own filters,
        # exactly as the catalogue endpoints do.
        if is_recommendation_eligible(product)
    )

    normalized = tuple(normalize_product(product) for product in candidates)
    # Style, room and feel are nobody's stated fact, so they arrive separately
    # and only when the sentence asked for one. A failed fetch is silent by
    # design: it costs ranking quality, never correctness.
    normalized = await attach_inferred_tags(
        normalized,
        gateway=tag_gateway,
        authenticated_request=authenticated_request,
        specification=parsed.specification,
    )
    # What this customer bought before, cached per user. It can only break
    # ties among products that already satisfy every stated constraint, and the
    # response says when it did; see app/personalization/profile.py.
    profile = await taste_profile(
        authenticated_request=authenticated_request,
        history=history_gateway,
        catalogue=gateway,
        caches=caches,
    )
    try:
        results = search_products(normalized, parsed.specification, profile)
    except ValueError:
        # Duplicate ids or an oversized candidate set: a catalogue problem, not
        # a client one.
        raise catalogue_upstream_error() from None

    # Only when nothing matched. With results on the page, near misses are
    # noise; with none, they are the difference between a dead end and a
    # decision the customer can make.
    alternatives = (
        nearest_alternatives(normalized, parsed.specification)
        if results.match_count == 0
        else ()
    )
    # Section 6.10's labelled seller half, on the same condition and in its own
    # list. Never shown beside real matches.
    offers = (
        await offering_gateway.published(authenticated_request=authenticated_request)
        if results.match_count == 0 and offering_gateway is not None
        else ()
    )

    return build_search_response(
        candidates,
        normalized=normalized,
        results=results,
        specification=parsed.specification,
        query=search_request.query,
        language=language,
        clarification=parsed.clarification,
        unresolved=parsed.unresolved,
        truncated=truncated,
        alternatives=alternatives,
        offers=offers,
        personalized=profile is not None
        and any(
            part.component == "taste" and part.value > 0
            for item in results.items
            for part in item.parts
        ),
    )
