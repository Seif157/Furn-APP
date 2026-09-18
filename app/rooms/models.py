"""The untrusted room draft, and the resolved room it becomes.

``RoomDraft`` is the only shape a provider's answer may take, and like the
search draft it has no field that could carry a marketplace fact: no product,
no seller, no price that exists. Quantities and the budget are what the
customer asked for, not what anything costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.ai.models import MAX_QUESTION_LENGTH, Surface, SurfaceList
from app.search.models import (
    HardConstraints,
    Language,
    QueryText,
    SoftPreferences,
    UnresolvedTerm,
)

MAX_ITEMS = 6
"""Kinds of furniture per room. Past this it is a shopping list, not a room."""
MAX_QUANTITY = 10


class RoomItemDraft(BaseModel):
    """One kind of furniture the customer asked for, as the provider read it."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    category: Surface | None = None
    quantity: Annotated[int, Field(ge=1, le=MAX_QUANTITY)] = 1
    colours: SurfaceList = ()
    """Preferences: a described colour ranks, it does not filter."""
    materials: SurfaceList = ()
    """Requirements: a customer who names a material rarely accepts another."""


class RoomDraft(BaseModel):
    """A whole room request, as the provider read it."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    items: Annotated[tuple[RoomItemDraft, ...], Field(max_length=MAX_ITEMS)] = ()
    max_budget: Decimal | None = None
    styles: SurfaceList = ()
    preferred_colours: SurfaceList = ()
    room_type: Surface | None = None
    clarification_question: (
        Annotated[str, Field(max_length=MAX_QUESTION_LENGTH)] | None
    ) = None


@dataclass(frozen=True, slots=True)
class RoomSlot:
    """One resolved kind of furniture: a real category, a quantity, criteria."""

    category: str
    quantity: int
    hard: HardConstraints
    soft: SoftPreferences


@dataclass(frozen=True, slots=True)
class RoomSpecification:
    """The validated room, ready for the planner."""

    slots: tuple[RoomSlot, ...]
    budget: Decimal | None
    query: QueryText
    language: Language
    styles: tuple[str, ...]
    room_type: str | None
    unresolved: tuple[UnresolvedTerm, ...]
    clarification: str | None
