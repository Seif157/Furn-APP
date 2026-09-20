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
from app.catalog.normalization import (
    CATEGORIES,
    COLOURS,
    FEELS,
    MATERIALS,
    ROOM_TYPES,
    STYLES,
    NormalizedProduct,
    Vocabulary,
)
from app.catalog.transform import build_product_response
from app.catalog.upstream_models import UpstreamProduct
from app.recommendations.alternatives import Alternative
from app.recommendations.explanations import (
    match_reasons,
    preference_reasons,
    shortfall_reasons,
)
from app.recommendations.models import AlternativeResponse, ReasonResponse
from app.recommendations.offerings import LABELS as OFFERING_LABELS
from app.recommendations.offerings import SellerOffering
from app.search.clarification import FollowUp, follow_up
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
    styles: tuple[TermResponse, ...]
    feels: tuple[TermResponse, ...]
    """How the customer wants it to feel. Ranked against inferred tags only,
    never filtered on."""
    room_type: TermResponse | None


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


class FollowUpOptionResponse(StrictResponseModel):
    """One tappable answer to the follow-up question."""

    value: str
    """Stable and machine-readable: a category slug, or a price band."""
    label: str
    """What to show on the chip, in the customer's language."""
    send: str
    """What to send as the next `query`, with this message in `history`.

    A tapped answer and a typed one take the same path through the parser, so
    the app needs no special case and the server needs no new state."""


class FollowUpResponse(StrictResponseModel):
    """A question with answers the customer can tap. Phase 7A.

    Present only when asking is worth it: the sentence was too vague to search,
    or it named no kind of furniture and matched broadly. Every option is built
    from products that actually matched, so tapping one cannot lead nowhere.
    """

    field: str
    question: str
    options: tuple[FollowUpOptionResponse, ...]


class SellerOfferResponse(StrictResponseModel):
    """A seller's made-to-order offering, shown only when nothing matched.

    Not a catalogue product: there is no stock, colour or delivery promise
    here, which is why it travels in its own list with its own label instead of
    among the results. Section 6.10.
    """

    id: str
    title: str
    description: str | None
    price: Decimal | None
    seller_id: str
    label: str
    """Says what this is, in the customer's language. Show it with the offer."""


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
    follow_up: FollowUpResponse | None
    """The same question with tappable answers, when one is worth asking."""
    unresolved: tuple[UnresolvedResponse, ...]
    excluded_by: tuple[ExclusionResponse, ...]
    """Why candidates were removed, most exclusions first."""
    alternatives: tuple[AlternativeResponse, ...]
    """Nearest real products, offered only when nothing matched. Phase 6.10."""
    seller_offers: tuple[SellerOfferResponse, ...]
    """Made-to-order offerings, also only when nothing matched. Never mixed
    into the results and never presented as catalogue products."""
    personalized: bool
    """True when this customer's own purchase history broke ties in the order.

    It never changed which products matched, only which of the matching ones
    came first."""


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
        styles=_terms(STYLES, soft.styles, language),
        feels=_terms(FEELS, soft.feels, language),
        room_type=(
            TermResponse(
                slug=soft.room_type,
                label=term_label(ROOM_TYPES, soft.room_type, language),
            )
            if soft.room_type is not None
            else None
        ),
    )


def _follow_up_response(asked: FollowUp | None) -> FollowUpResponse | None:
    if asked is None:
        return None
    return FollowUpResponse(
        field=asked.field,
        question=asked.question,
        options=tuple(
            FollowUpOptionResponse(
                value=option.value, label=option.label, send=option.send
            )
            for option in asked.options
        ),
    )


def build_search_response(
    products: tuple[UpstreamProduct, ...],
    *,
    normalized: tuple[NormalizedProduct, ...] = (),
    offers: tuple[SellerOffering, ...] = (),
    personalized: bool = False,
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
    normalized_by_id = {product.id: product for product in normalized}
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
                # Catalogue facts first, then the platform's own guesses about
                # style, room and feel, each marked as one.
                reasons=match_reasons(scored.checks, specification.hard, language)
                + (
                    preference_reasons(
                        normalized_by_id[scored.product_id],
                        specification.soft,
                        language,
                    )
                    if scored.product_id in normalized_by_id
                    else ()
                ),
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

    asked = follow_up(
        specification=specification,
        matches=tuple(
            normalized_by_id[scored.product_id]
            for scored in results.items
            if scored.product_id in normalized_by_id
        ),
        match_count=results.match_count,
        clarification=clarification,
        language=language,
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
        follow_up=_follow_up_response(asked),
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
        seller_offers=tuple(
            SellerOfferResponse(
                id=str(offer.id),
                title=offer.title,
                description=offer.description,
                price=offer.price,
                seller_id=str(offer.seller_id),
                label=OFFERING_LABELS[response_language(language)],
            )
            for offer in offers
        ),
        personalized=personalized,
    )
