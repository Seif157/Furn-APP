"""The untrusted boundary between model output and business logic.

``RequirementDraft`` is the only shape a provider's answer is allowed to take.
It carries language, not marketplace facts: category and attribute words the
user used, numeric bounds the user stated, and nothing else. There is no field
for a product id, a seller, a stock count, a title, or a publication state, so
a hallucinated product has nowhere to travel. That is a structural guarantee,
not a rule the prompt asks the model to follow.

The draft is lenient about JSON types, because the input is foreign JSON and an
integer where a decimal was expected is not an attack. It is strict about
everything that constrains meaning: value ranges, list lengths, and string
lengths. Unknown keys are dropped rather than rejected, since a provider adding
a field should not break parsing and a dropped field cannot reach the catalogue.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.search.models import MAX_TERMS, SearchSpecification, UnresolvedTerm

MAX_SURFACE_LENGTH = 80
MAX_QUESTION_LENGTH = 300

Surface = Annotated[str, Field(max_length=MAX_SURFACE_LENGTH)]
SurfaceList = Annotated[tuple[Surface, ...], Field(max_length=MAX_TERMS)]


class RequirementDraft(BaseModel):
    """One sentence's requirements, as the provider understood them."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    category: Surface | None = None
    required_colours: SurfaceList = ()
    required_materials: SurfaceList = ()

    min_price: Decimal | None = None
    max_price: Decimal | None = None
    min_width_cm: Decimal | None = None
    max_width_cm: Decimal | None = None
    min_height_cm: Decimal | None = None
    max_height_cm: Decimal | None = None
    min_depth_cm: Decimal | None = None
    max_depth_cm: Decimal | None = None
    in_stock_only: bool = True

    preferred_colours: SurfaceList = ()
    preferred_materials: SurfaceList = ()
    styles: SurfaceList = ()
    feels: SurfaceList = ()
    room_type: Surface | None = None
    preferred_width_cm: Decimal | None = None
    preferred_height_cm: Decimal | None = None
    preferred_depth_cm: Decimal | None = None
    target_price: Decimal | None = None

    clarification_question: (
        Annotated[str, Field(max_length=MAX_QUESTION_LENGTH)] | None
    ) = None
    """Set only when the sentence is too vague to search; otherwise null."""


class ParsedRequirements(BaseModel):
    """What the backend hands to retrieval after a sentence has been parsed."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    specification: SearchSpecification
    unresolved: tuple[UnresolvedTerm, ...] = ()
    """Words the vocabularies could not map. Reported, never guessed."""
    clarification: str | None = None
    """The question to ask when the sentence was too vague to search."""
