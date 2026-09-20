"""Client-facing models for the two intake endpoints."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.catalog.models import StrictResponseModel
from app.search.responses import TermResponse, UnresolvedResponse


class ServiceMatchResponse(StrictResponseModel):
    """A real service from the marketplace's own directory.

    ``id`` and ``name`` are the row's own values, read with the customer's
    token. ``confidence`` is the model's, and is the only judgement here.
    """

    id: UUID
    name: str
    description: str | None
    confidence: Decimal
    """Between 0 and 1: how sure the match is. Show the list, not one answer."""


class ServiceTriageResponse(StrictResponseModel):
    """Which services fit a described problem. Nothing is created."""

    language: str
    services: tuple[ServiceMatchResponse, ...]
    """Ranked, most fitting first. Empty means the marketplace does not offer
    it, which is an answer and not a failure."""
    clarification: str | None
    """Asked only when one detail would decide between two services."""


class BriefRoomResponse(StrictResponseModel):
    room_type: TermResponse
    quantity: int


class BriefResponse(StrictResponseModel):
    """A furnishing job read into the request form's own fields."""

    language: str
    rooms: tuple[BriefRoomResponse, ...]
    total_budget: Decimal | None
    """For the whole job, in EGP, only when the customer stated one."""
    styles: tuple[TermResponse, ...]
    feels: tuple[TermResponse, ...]
    unresolved: tuple[UnresolvedResponse, ...]
    """Words the vocabularies did not recognise, reported rather than guessed."""
    clarification: str | None
