"""Deterministic validation between a provider's draft and a real search.

Everything the model said is re-decided here. Words become slugs only if the
Phase 4B vocabularies recognise them, and numbers survive only if they pass the
same bounds a hand-built specification passes.

Hard constraints and soft preferences fail differently, on purpose:

  A bad hard constraint rejects the whole draft. Silently dropping "under
  30,000" turns a budget search into an unbounded one, and the customer sees
  products they ruled out. Failing loudly is the safer half of that trade.

  A bad soft preference is dropped. It only orders results that are already
  correct, so discarding it costs relevance, never correctness.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import ValidationError

from app.ai.models import RequirementDraft
from app.ai.provider import AIResponseInvalidError
from app.search.models import (
    DEFAULT_RESULTS,
    MAX_DIMENSION_CM,
    MAX_PRICE,
    DimensionRange,
    PriceRange,
    SpecificationBuild,
    build_specification,
)


class RequirementDraftError(AIResponseInvalidError):
    """Raised when a draft cannot become a specification without distortion."""


def _price_range(minimum: Decimal | None, maximum: Decimal | None) -> PriceRange | None:
    if minimum is None and maximum is None:
        return None
    try:
        return PriceRange(minimum=minimum, maximum=maximum)
    except ValidationError:
        raise RequirementDraftError from None


def _dimension_range(
    minimum: Decimal | None, maximum: Decimal | None
) -> DimensionRange | None:
    if minimum is None and maximum is None:
        return None
    try:
        return DimensionRange(minimum_cm=minimum, maximum_cm=maximum)
    except ValidationError:
        raise RequirementDraftError from None


def _soft_value(value: Decimal | None, *, high: Decimal) -> Decimal | None:
    """Keep a preference only if it is finite, positive, and in range."""

    if value is None:
        return None
    if not value.is_finite() or value <= 0 or value > high:
        return None
    return value


def _terms(surfaces: tuple[str, ...]) -> tuple[str, ...]:
    """Drop blanks, which carry no meaning and cannot be looked up."""

    return tuple(surface for surface in surfaces if surface.strip())


def specification_from_draft(
    draft: RequirementDraft,
    *,
    query: str,
    limit: int = DEFAULT_RESULTS,
) -> SpecificationBuild:
    """Resolve a draft into a validated specification and its unresolved terms."""

    category = draft.category.strip() if draft.category else None
    room_type = draft.room_type.strip() if draft.room_type else None

    try:
        return build_specification(
            category=category or None,
            colours=_terms(draft.required_colours),
            materials=_terms(draft.required_materials),
            price=_price_range(draft.min_price, draft.max_price),
            width=_dimension_range(draft.min_width_cm, draft.max_width_cm),
            height=_dimension_range(draft.min_height_cm, draft.max_height_cm),
            depth=_dimension_range(draft.min_depth_cm, draft.max_depth_cm),
            in_stock_only=draft.in_stock_only,
            preferred_colours=_terms(draft.preferred_colours),
            preferred_materials=_terms(draft.preferred_materials),
            styles=_terms(draft.styles),
            feels=_terms(draft.feels),
            room_type=room_type or None,
            preferred_width_cm=_soft_value(
                draft.preferred_width_cm, high=MAX_DIMENSION_CM
            ),
            preferred_height_cm=_soft_value(
                draft.preferred_height_cm, high=MAX_DIMENSION_CM
            ),
            preferred_depth_cm=_soft_value(
                draft.preferred_depth_cm, high=MAX_DIMENSION_CM
            ),
            target_price=_soft_value(draft.target_price, high=MAX_PRICE),
            query=query,
            limit=limit,
        )
    except ValidationError:
        # Anything the specification models still refuse: a style that
        # normalizes away to nothing, a limit out of range, a combination the
        # hand-built path would also reject.
        raise RequirementDraftError from None
