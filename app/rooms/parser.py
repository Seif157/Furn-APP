"""Turn one room sentence into a validated ``RoomSpecification``.

The same guardrails as search, applied per piece of furniture. Every category,
colour and material the model returns is resolved by the Phase 4B vocabularies
or reported as unresolved, never mapped to a near neighbour. A bad budget
rejects the draft, because silently dropping "under 40,000" would plan a room
the customer ruled out.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import ValidationError

from app.ai.guardrails import RequirementDraftError
from app.ai.provider import AIProvider
from app.ai.service import validate_query
from app.catalog.normalization import (
    CATEGORIES,
    COLOURS,
    MATERIALS,
    Vocabulary,
    normalize_text,
)
from app.rooms.models import (
    MAX_QUANTITY,
    RoomDraft,
    RoomItemDraft,
    RoomSlot,
    RoomSpecification,
)
from app.rooms.prompts import ROOM_INSTRUCTION, ROOM_SCHEMA
from app.search.models import (
    MAX_PRICE,
    MAX_TERMS,
    HardConstraints,
    SoftPreferences,
    SpecificationField,
    UnresolvedTerm,
    detect_language,
    query_text,
)


class RoomDraftError(RequirementDraftError):
    """Raised when a room draft cannot be planned without distortion."""


def _resolve(
    vocabulary: Vocabulary,
    surfaces: Iterable[str],
    *,
    field: SpecificationField,
    unresolved: list[UnresolvedTerm],
) -> tuple[str, ...]:
    slugs: list[str] = []
    for surface in (s.strip() for s in surfaces):
        if not surface:
            continue
        term = vocabulary.lookup(surface)
        if term is None:
            unresolved.append(UnresolvedTerm(field=field, surface=surface))
        elif term.slug not in slugs:
            slugs.append(term.slug)
    return tuple(slugs)


def _normalized(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(normalize_text(v) for v in values if normalize_text(v)))[
        :MAX_TERMS
    ]


def specification_from_room_draft(draft: RoomDraft, *, query: str) -> RoomSpecification:
    """Resolve a room draft into slots, merging repeated kinds of furniture."""

    unresolved: list[UnresolvedTerm] = []

    budget = draft.max_budget
    if budget is not None and (
        not budget.is_finite() or budget <= 0 or budget > MAX_PRICE
    ):
        raise RoomDraftError

    room_colours = _resolve(
        COLOURS,
        draft.preferred_colours,
        field="preferred_colours",
        unresolved=unresolved,
    )
    styles = _normalized(draft.styles)
    room_type = normalize_text(draft.room_type) if draft.room_type else None

    # Merged by resolved category, so "a chair ... and another chair" is one
    # slot of two. Two slots of the same category could otherwise pick two
    # different chairs for what the customer meant as a matching pair.
    merged: dict[str, tuple[int, list[str], list[str]]] = {}
    for item in draft.items:
        surface = (item.category or "").strip()
        if not surface:
            continue
        term = CATEGORIES.lookup(surface)
        if term is None:
            unresolved.append(UnresolvedTerm(field="category", surface=surface))
            continue
        materials = _resolve(
            MATERIALS, item.materials, field="materials", unresolved=unresolved
        )
        colours = _resolve(
            COLOURS, item.colours, field="preferred_colours", unresolved=unresolved
        )
        quantity, known_materials, known_colours = merged.get(term.slug, (0, [], []))
        merged[term.slug] = (
            quantity + item.quantity,
            [*known_materials, *(m for m in materials if m not in known_materials)],
            [*known_colours, *(c for c in colours if c not in known_colours)],
        )

    slots: list[RoomSlot] = []
    try:
        for slug, (quantity, materials, colours) in merged.items():
            if quantity > MAX_QUANTITY:
                raise RoomDraftError
            slot_colours = tuple(dict.fromkeys([*colours, *room_colours]))[:MAX_TERMS]
            slots.append(
                RoomSlot(
                    category=slug,
                    quantity=quantity,
                    hard=HardConstraints(
                        category=slug,
                        materials=tuple(materials)[:MAX_TERMS],
                        in_stock_only=True,
                    ),
                    soft=SoftPreferences(
                        colours=slot_colours,
                        styles=styles,
                        room_type=room_type,
                    ),
                )
            )
    except ValidationError:
        raise RoomDraftError from None

    clarification = (
        draft.clarification_question.strip() or None
        if draft.clarification_question
        else None
    )
    return RoomSpecification(
        slots=tuple(slots),
        budget=budget,
        query=query_text(query),
        language=detect_language(query),
        styles=styles,
        room_type=room_type,
        unresolved=tuple(unresolved),
        clarification=clarification,
    )


async def parse_room_request(text: str, *, provider: AIProvider) -> RoomSpecification:
    """Parse one room sentence. Raises the same errors as search parsing."""

    query = validate_query(text)
    raw = await provider.generate_json(
        instruction=ROOM_INSTRUCTION, prompt=query, schema=ROOM_SCHEMA
    )
    try:
        draft = RoomDraft.model_validate(dict(raw))
    except ValidationError:
        raise RoomDraftError from None
    return specification_from_room_draft(draft, query=query)


__all__ = [
    "RoomDraftError",
    "RoomItemDraft",
    "parse_room_request",
    "specification_from_room_draft",
]
