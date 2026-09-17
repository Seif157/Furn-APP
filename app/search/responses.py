"""Stable client-facing models for natural-language search (Phase 5C).

``results.py`` holds the internal scoring result, which carries weights, score
components, and rejection counts that exist to make ranking testable. This
module holds what Flutter sees. Keeping them apart means the ranking internals
can change without breaking a client.

Every product fact in a response comes from ``build_product_response``, the
same transform the catalogue endpoints use, so search cannot expose a field
the catalogue would have withheld.

Terms carry a slug and a label. The slug is stable and is what a client should
branch on; the label is display text in the customer's own language, taken from
the Phase 4B vocabularies rather than translated at request time.
"""

from __future__ import annotations

from decimal import Decimal

from app.catalog.models import ProductResponse, StrictResponseModel
from app.catalog.normalization import CATEGORIES, COLOURS, MATERIALS, Vocabulary
from app.catalog.transform import build_product_response
from app.catalog.upstream_models import UpstreamProduct
from app.recommendations.alternatives import Alternative
from app.recommendations.explanations import match_reasons, shortfall_reasons
from app.recommendations.models import AlternativeResponse, ReasonResponse
from app.search.localization import response_language, term_label
from app.search.models import (
    DimensionRange,
    Language,
    PriceRange,
    SearchSpecification,
    UnresolvedTerm,
)
from app.search.results import SearchResults


class TermResponse(StrictResponseModel):
    """A resolved vocabulary term: a stable slug and a label to show."""

    slug: str
    label: str


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

    category: TermResponse | None
    colours: tuple[TermResponse, ...]
    materials: tuple[TermResponse, ...]
    price: RangeResponse | None
    width_cm: RangeResponse | None
    height_cm: RangeResponse | None
    depth_cm: RangeResponse | None
    in_stock_only: bool
    preferred_colours: tuple[TermResponse, ...]
    preferred_materials: tuple[TermResponse, ...]
    styles: tuple[str, ...]
    """Matching keys against enrichment attributes, not display labels, so
    these stay in English in every language."""
    room_type: str | None


class UnresolvedResponse(StrictResponseModel):
    """A word the vocabularies did not recognise, reported rather than guessed."""

    field: str
    surface: str


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


class SearchItemResponse(StrictResponseModel):
    """One matching product and the grounded reason it matched."""

    product: ProductResponse
    score: Decimal
    """Between 0 and 1. Soft-preference fit only; every item passed every
    hard constraint, so this never explains exclusion."""
    matched: tuple[str, ...]
    """The hard constraints this product was checked against and satisfied."""
    reasons: tuple[ReasonResponse, ...]
    """Why it matches, as catalogue facts. Phase 6C; never model prose."""


class SearchResponse(StrictResponseModel):
    query: str
    language: str
    """The language this response speaks: "ar" or "en"."""
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
    alternatives: tuple[AlternativeResponse, ...]
    """Nearest real products, offered only when nothing matched. Phase 6.10."""


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


def _terms(
    vocabulary: Vocabulary, slugs: tuple[str, ...], language: Language
) -> tuple[TermResponse, ...]:
    return tuple(
        TermResponse(slug=slug, label=term_label(vocabulary, slug, language))
        for slug in slugs
    )


def build_interpretation(
    specification: SearchSpecification, language: Language
) -> InterpretationResponse:
    """Describe the executed specification in the customer's own language."""

    hard = specification.hard
    soft = specification.soft
    category = (
        TermResponse(
            slug=hard.category,
            label=term_label(CATEGORIES, hard.category, language),
        )
        if hard.category is not None
        else None
    )
    return InterpretationResponse(
        category=category,
        colours=_terms(COLOURS, hard.colours, language),
        materials=_terms(MATERIALS, hard.materials, language),
        price=_price_range(hard.price),
        width_cm=_dimension_range(hard.width),
        height_cm=_dimension_range(hard.height),
        depth_cm=_dimension_range(hard.depth),
        in_stock_only=hard.in_stock_only,
        preferred_colours=_terms(COLOURS, soft.colours, language),
        preferred_materials=_terms(MATERIALS, soft.materials, language),
        styles=soft.styles,
        room_type=soft.room_type,
    )


def build_search_response(
    products: tuple[UpstreamProduct, ...],
    *,
    results: SearchResults,
    specification: SearchSpecification,
    query: str,
    language: Language,
    clarification: str | None,
    unresolved: tuple[UnresolvedTerm, ...],
    truncated: bool,
    alternatives: tuple[Alternative, ...] = (),
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
                reasons=match_reasons(scored.checks, specification.hard, language),
            )
        )

    offered: list[AlternativeResponse] = []
    for alternative in alternatives:
        upstream = by_id.get(alternative.product.id)
        if upstream is None:
            continue
        # An alternative goes through the same transform as a result, so a row
        # the catalogue would withhold cannot reach a client by this route.
        response = build_product_response(upstream)
        if response is None:
            continue
        offered.append(
            AlternativeResponse(
                product=response,
                missed=shortfall_reasons(
                    alternative.checks, specification.hard, language
                ),
                missed_count=len(alternative.missed),
            )
        )

    return SearchResponse(
        query=query,
        language=response_language(language),
        interpretation=build_interpretation(specification, language),
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
        alternatives=tuple(offered),
    )
