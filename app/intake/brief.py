"""Turn "I want to furnish a three-bedroom flat" into a request form.

A furnishing request is answered by a seller, not by the catalogue, so nothing
here picks a product or quotes a price. It reads one description into the
fields the request form already has: which rooms, how many of each, the budget
for the whole job, and the look the customer is after.

Rooms, styles and feels resolve through the same vocabularies search uses, so
the brief a seller reads and the search a customer runs mean the same words.
Anything outside them is reported as unresolved rather than mapped to a near
neighbour, exactly as in the search parser and for the same reason: a nearby
word is a different room.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.provider import AIProvider, AIResponseInvalidError
from app.ai.service import conversation
from app.catalog.normalization import FEELS, ROOM_TYPES, STYLES, Vocabulary
from app.search.models import MAX_PRICE, MAX_TERMS, UnresolvedTerm

MAX_ROOMS = 8
MAX_ROOM_QUANTITY = 10
MAX_SURFACE_LENGTH = 80
MAX_QUESTION_LENGTH = 300


class RoomRequest(BaseModel):
    """One room the customer wants furnished, as the provider understood it."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    room: Annotated[str, Field(max_length=MAX_SURFACE_LENGTH)] = ""
    quantity: int | None = None


class BriefDraft(BaseModel):
    """What the provider answered, before any of it is believed."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    rooms: Annotated[tuple[RoomRequest, ...], Field(max_length=MAX_ROOMS)] = ()
    total_budget: Decimal | None = None
    styles: Annotated[
        tuple[Annotated[str, Field(max_length=MAX_SURFACE_LENGTH)], ...],
        Field(max_length=MAX_TERMS),
    ] = ()
    feels: Annotated[
        tuple[Annotated[str, Field(max_length=MAX_SURFACE_LENGTH)], ...],
        Field(max_length=MAX_TERMS),
    ] = ()
    clarification_question: (
        Annotated[str, Field(max_length=MAX_QUESTION_LENGTH)] | None
    ) = None


@dataclass(frozen=True, slots=True)
class BriefRoom:
    room_type: str
    quantity: int


@dataclass(frozen=True, slots=True)
class FurnishingBrief:
    rooms: tuple[BriefRoom, ...]
    total_budget: Decimal | None
    styles: tuple[str, ...]
    feels: tuple[str, ...]
    unresolved: tuple[UnresolvedTerm, ...]
    clarification: str | None


BRIEF_INSTRUCTION = f"""\
You read one description of a furnishing job for an Egyptian furniture
marketplace and fill in a request form. Customers write in Arabic, in English,
or in a mix of both.

Return only what the description says. Never invent a room, a budget, or a
style the customer did not mention; an empty answer is correct for a
description that says nothing definite.

  rooms: each room to be furnished, with how many of it there are. "شقة ٣ أوض
  نوم وريسبشن" is three bedrooms and one reception. Copy the customer's own
  word for the room; do not translate it into the nearest one you know.
  At most {MAX_ROOMS} entries, and a quantity between 1 and {MAX_ROOM_QUANTITY}.

  total_budget: a plain number of Egyptian pounds for the whole job, only when
  the customer states one. Read "١٥٠ ألف" and "150k" as 150000. Never derive a
  budget from the size of the flat.

  styles and feels: how they want it to look and to feel, in their own words.
  Both are preferences.

Set clarification_question only when the description names no room at all and
no budget, so there is nothing to put on the form. Write it in the customer's
own language: Egyptian Arabic if their words contain any Arabic, otherwise
English. Otherwise leave it null. Ask at most one question, under
{MAX_QUESTION_LENGTH} characters.

You never name a product, a seller, a price that exists, or a delivery date.
You restate what the customer asked for, nothing else.
"""

_SURFACE_LIST: dict[str, Any] = {
    "type": "ARRAY",
    "maxItems": MAX_TERMS,
    "items": {"type": "STRING", "maxLength": MAX_SURFACE_LENGTH},
}

BRIEF_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "rooms": {
            "type": "ARRAY",
            "maxItems": MAX_ROOMS,
            "items": {
                "type": "OBJECT",
                "properties": {
                    "room": {"type": "STRING", "maxLength": MAX_SURFACE_LENGTH},
                    "quantity": {"type": "INTEGER"},
                },
                "propertyOrdering": ["room", "quantity"],
            },
        },
        "total_budget": {"type": "NUMBER", "nullable": True},
        "styles": _SURFACE_LIST,
        "feels": _SURFACE_LIST,
        "clarification_question": {
            "type": "STRING",
            "nullable": True,
            "maxLength": MAX_QUESTION_LENGTH,
        },
    },
    "propertyOrdering": list(BriefDraft.model_fields),
}


def _resolve(
    surfaces: Sequence[str],
    vocabulary: Vocabulary,
    field: str,
    unresolved: list[UnresolvedTerm],
) -> tuple[str, ...]:
    slugs: list[str] = []
    for surface in surfaces:
        cleaned = surface.strip()
        if not cleaned:
            continue
        term = vocabulary.lookup(cleaned)
        if term is None:
            unresolved.append(UnresolvedTerm(field=field, surface=cleaned))  # type: ignore[arg-type]
        elif term.slug not in slugs:
            slugs.append(term.slug)
    return tuple(slugs)


def brief_from_draft(draft: BriefDraft) -> FurnishingBrief:
    """Resolve a draft into a form the marketplace can actually store."""

    unresolved: list[UnresolvedTerm] = []
    rooms: dict[str, int] = {}
    for entry in draft.rooms:
        cleaned = entry.room.strip()
        if not cleaned:
            continue
        term = ROOM_TYPES.lookup(cleaned)
        if term is None:
            unresolved.append(UnresolvedTerm(field="room_type", surface=cleaned))
            continue
        quantity = entry.quantity if entry.quantity is not None else 1
        if quantity < 1 or quantity > MAX_ROOM_QUANTITY:
            # A stated quantity out of range is not a reason to drop the room;
            # the room was asked for either way. The count falls back to one,
            # which is the smallest claim that stays true.
            quantity = 1
        rooms[term.slug] = max(rooms.get(term.slug, 0), quantity)

    budget = draft.total_budget
    if budget is not None and (
        not budget.is_finite() or budget <= 0 or budget > MAX_PRICE
    ):
        budget = None

    question = (
        draft.clarification_question.strip() or None
        if draft.clarification_question
        else None
    )
    return FurnishingBrief(
        rooms=tuple(
            BriefRoom(room_type=slug, quantity=quantity)
            for slug, quantity in sorted(rooms.items())
        ),
        total_budget=budget,
        styles=_resolve(draft.styles, STYLES, "styles", unresolved),
        feels=_resolve(draft.feels, FEELS, "feels", unresolved),
        unresolved=tuple(unresolved),
        clarification=question,
    )


async def read_brief(
    description: str,
    *,
    provider: AIProvider,
    history: Sequence[str] = (),
) -> FurnishingBrief:
    """Read one description into a furnishing brief. Raises the parser errors."""

    turn = conversation(BRIEF_INSTRUCTION, description, history)
    raw = await provider.generate_json(
        instruction=turn.instruction,
        prompt=turn.prompt,
        schema=BRIEF_SCHEMA,
    )
    try:
        draft = BriefDraft.model_validate(dict(raw))
    except ValidationError:
        raise AIResponseInvalidError from None
    return brief_from_draft(draft)
