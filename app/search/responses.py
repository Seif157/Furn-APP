"""Stable client-facing models for natural-language search (Phase 5C).

``results.py`` holds the internal scoring result, which carries weights, score
components, and rejection counts that exist to make ranking testable. This
module holds what Flutter sees. Keeping them apart means the ranking internals
can change without breaking a client.

Every product fact in a response comes from ``build_product_response``, the
same transform the catalogue endpoints use, so search cannot expose a field
the catalogue would have withheld.
"""

from __future__ import annotations

from decimal import Decimal

from app.catalog.models import ProductResponse, StrictResponseModel
from app.catalog.transform import build_product_response
from app.catalog.upstream_models import UpstreamProduct
from app.search.models import (
    DimensionRange,
    PriceRange,
    SearchSpecification,
    UnresolvedTerm,
)
from app.search.results import SearchResults


class RangeResponse(StrictResponseModel):
    """An inclusive bound the customer stated. Units follow the field name."""

    minimum: Decimal | None
    maximum: Decimal | None


class InterpretationResponse(StrictResponseModel):
    """What the backend understood the sentence to mean.

    Returned so a client can show the customer what was understood, and
    correct it. Every value here survived vocabulary resolution and bounds
    checking, so it is what the search actually ran.
    """

    category: str | None
    colours: tuple[str, ...]
    materials: tuple[str, ...]
    price: RangeResponse | None
    width_cm: RangeResponse | None
    height_cm: RangeResponse | None
    depth_cm: RangeResponse | None
    in_stock_only: bool
    preferred_colours: tuple[str, ...]
    preferred_materials: tuple[str, ...]
    styles: tuple[str, ...]
    room_type: str | None


class UnresolvedResponse(StrictResponseModel):
    """A word the vocabularies did not recognise, reported rather than guessed."""

    field: str
    surface: str


class SearchItemResponse(StrictResponseModel):
    """One matching product and the grounded reason it matched."""

    product: ProductResponse
    score: Decimal
    """Between 0 and 1. Soft-preference fit only; every item passed every
    hard constraint, so this never explains exclusion."""
    matched: tuple[str, ...]
    """The hard constraints this product was checked against and satisfied."""


class ExclusionResponse(StrictResponseModel):
    """How many candidates this one hard constraint would have removed.

    Deterministic, and the honest answer to "why did I get nothing?". Phase 4D
    already counts this while filtering, so surfacing it costs nothing and
    turns an empty result from a dead end into a reason.

    The counts overlap and do not sum to the number excluded. A product that
    is both the wrong category and over budget is counted under each, which is
    what makes the largest count the binding constraint to relax first.
    """

    constraint: str
    excluded: int


class SearchResponse(StrictResponseModel):
    query: str
    interpretation: InterpretationResponse
    items: tuple[SearchItemResponse, ...]
    limit: int
    match_count: int
    candidate_count: int
    truncated: bool
    """True when more eligible products existed than search examined."""
    has_more: bool
    clarification: str | None
    """A question to ask when the sentence was too vague to search."""
    unresolved: tuple[UnresolvedResponse, ...]
    excluded_by: tuple[ExclusionResponse, ...]
    """Why candidates were removed, most exclusions first."""


def _price_range(bounds: PriceRange | None) -> RangeResponse | None:
    if bounds is None:
        return None
    return RangeResponse(minimum=bounds.minimum, maximum=bounds.maximum)


def _dimension_range(bounds: DimensionRange | None) -> RangeResponse | None:
    # The two range types name their bounds differently and a zero bound is
    # legal, so these read the fields by name rather than by truthiness.
    if bounds is None:
        return None
    return RangeResponse(minimum=bounds.minimum_cm, maximum=bounds.maximum_cm)


def build_interpretation(
    specification: SearchSpecification,
) -> InterpretationResponse:
    """Describe the executed specification in client-facing terms."""

    hard = specification.hard
    soft = specification.soft
    return InterpretationResponse(
        category=hard.category,
        colours=hard.colours,
        materials=hard.materials,
        price=_price_range(hard.price),
        width_cm=_dimension_range(hard.width),
        height_cm=_dimension_range(hard.height),
        depth_cm=_dimension_range(hard.depth),
        in_stock_only=hard.in_stock_only,
        preferred_colours=soft.colours,
        preferred_materials=soft.materials,
        styles=soft.styles,
        room_type=soft.room_type,
    )


def build_search_response(
    products: tuple[UpstreamProduct, ...],
    *,
    results: SearchResults,
    specification: SearchSpecification,
    query: str,
    clarification: str | None,
    unresolved: tuple[UnresolvedTerm, ...],
    truncated: bool,
) -> SearchResponse:
    """Compose the response, keeping ranking order and dropping what cannot ship.

    A product that the catalogue transform refuses is dropped rather than
    partially rendered, so an ineligible record cannot reach a client through
    the search path after passing the search path's own filters.
    """

    by_id = {product.id: product for product in products}
    items: list[SearchItemResponse] = []
    for scored in results.items:
        product = by_id.get(scored.product_id)
        if product is None:
            continue
        response = build_product_response(product)
        if response is None:
            continue
        items.append(
            SearchItemResponse(
                product=response,
                score=scored.score,
                matched=tuple(check.name for check in scored.checks if check.satisfied),
            )
        )

    return SearchResponse(
        query=query,
        interpretation=build_interpretation(specification),
        items=tuple(items),
        limit=results.limit,
        match_count=results.match_count,
        candidate_count=results.candidate_count,
        truncated=truncated,
        has_more=results.has_more,
        clarification=clarification,
        unresolved=tuple(
            UnresolvedResponse(field=term.field, surface=term.surface)
            for term in unresolved
        ),
        excluded_by=tuple(
            ExclusionResponse(constraint=name, excluded=count)
            for name, count in sorted(
                results.rejections, key=lambda item: (-item[1], item[0])
            )
        ),
    )
