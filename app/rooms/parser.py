"""Turn one room sentence into a validated ``RoomSpecification``.

The same guardrails as search, applied per piece of furniture. Every category,
colour and material the model returns is resolved by the Phase 4B vocabularies
or reported as unresolved, never mapped to a near neighbour. A bad budget
rejects the draft, because silently dropping "under 40,000" would plan a room
the customer ruled out.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal

from pydantic import ValidationError

from app.ai.guardrails import RequirementDraftError
from app.ai.provider import AIProvider
from app.ai.service import conversation
from app.catalog.normalization import (
    CATEGORIES,
    COLOURS,
    MATERIALS,
    ROOM_TYPES,
    STYLES,
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
    QueryText,
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


def _checked_budget(value: Decimal | None) -> Decimal | None:
    """A stated budget must be usable, or the whole draft is refused.

    Dropping an unusable one would plan as if no limit had been stated, and
    show the customer a room they ruled out.
    """

    if value is None:
        return None
    if not value.is_finite() or value <= 0 or value > MAX_PRICE:
        raise RoomDraftError
    # A model may answer 12000.0; a customer reads "12000".
    return value.quantize(Decimal(1)) if value == value.to_integral_value() else value


# Count words say how many, not which one. Left in the scoring query, "two
# chairs" matched a sofa described as "two-seat" and let it tie with the modern
# sofa the customer asked for. Normalized forms.
COUNT_WORDS = frozenset(
    {
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "pair",
        "couple",
        "single",
        "واحد",
        "واحده",
        "اتنين",
        "اثنين",
        "تنين",
        "تلاته",
        "ثلاثه",
        "تلات",
        "اربعه",
        "اربع",
        "خمسه",
        "خمس",
        "سته",
        "ست",
        "سبعه",
        "تمانيه",
        "تسعه",
        "عشره",
        "جوز",
    }
)


def _scoring_query(text: str) -> QueryText:
    kept = " ".join(
        word
        for word in text.split()
        if normalize_text(word.strip(".,،:;!?")) not in COUNT_WORDS
    )
    return query_text(kept or text)


def specification_from_room_draft(draft: RoomDraft, *, query: str) -> RoomSpecification:
    """Resolve a room draft into slots, merging repeated kinds of furniture."""

    unresolved: list[UnresolvedTerm] = []

    budget = _checked_budget(draft.max_budget)

    room_colours = _resolve(
        COLOURS,
        draft.preferred_colours,
        field="preferred_colours",
        unresolved=unresolved,
    )
    # Styles and rooms are vocabulary slugs, like colours and materials, so
    # that the room planner and search mean the same words. Free text here
    # reached SoftPreferences unresolved and was refused as an untrustworthy
    # answer: a live room plan returned 502 for "أوضة معيشة" on 2026-09-20.
    styles = _resolve(STYLES, draft.styles, field="styles", unresolved=unresolved)
    room_types = _resolve(
        ROOM_TYPES,
        (draft.room_type,) if draft.room_type else (),
        field="room_type",
        unresolved=unresolved,
    )
    room_type = room_types[0] if room_types else None

    # Merged by resolved category, so "a chair ... and another chair" is one
    # slot of two. Two slots of the same category could otherwise pick two
    # different chairs for what the customer meant as a matching pair.
    merged: dict[str, tuple[int, list[str], list[str], list[Decimal | None]]] = {}
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
        quantity, known_materials, known_colours, budgets = merged.get(
            term.slug, (0, [], [], [])
        )
        merged[term.slug] = (
            quantity + item.quantity,
            [*known_materials, *(m for m in materials if m not in known_materials)],
            [*known_colours, *(c for c in colours if c not in known_colours)],
            [*budgets, _checked_budget(item.max_budget)],
        )

    slots: list[RoomSlot] = []
    try:
        for slug, (quantity, materials, colours, budgets) in merged.items():
            # Merged lines add their budgets only when every part had one. If
            # one mention had a budget and another did not, the limit for the
            # combined line is unknown, so none is invented.
            line_budget = (
                sum(budgets, Decimal("0"))
                if budgets and all(b is not None for b in budgets)
                else None
            )
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
                    budget=line_budget,
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
        scoring_query=_scoring_query(query),
        language=detect_language(query),
        styles=styles,
        room_type=room_type,
        unresolved=tuple(unresolved),
        clarification=clarification,
    )


async def parse_room_request(
    text: str, *, provider: AIProvider, history: Sequence[str] = ()
) -> RoomSpecification:
    """Parse one room sentence, optionally refining earlier ones.

    Raises the same errors as search parsing. With no history the model gets
    exactly the instruction and prompt it always did.
    """

    turn = conversation(ROOM_INSTRUCTION, text, history)
    raw = await provider.generate_json(
        instruction=turn.instruction, prompt=turn.prompt, schema=ROOM_SCHEMA
    )
    try:
        draft = RoomDraft.model_validate(dict(raw))
    except ValidationError:
        raise RoomDraftError from None
    return specification_from_room_draft(draft, query=turn.query)


__all__ = [
    "RoomDraftError",
    "RoomItemDraft",
    "parse_room_request",
    "specification_from_room_draft",
]
