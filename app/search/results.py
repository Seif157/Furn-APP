"""Result models for deterministic structured search (Phase 4D)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

ConstraintName = Literal[
    "category",
    "colours",
    "materials",
    "price",
    "width",
    "height",
    "depth",
    "in_stock",
]
ScoreComponent = Literal[
    "colours",
    "materials",
    "styles",
    "room_type",
    "width",
    "height",
    "depth",
    "price",
    "query",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        allow_inf_nan=False, extra="forbid", frozen=True, strict=True
    )


class ConstraintCheck(StrictModel):
    """One hard constraint evaluated against one product."""

    name: ConstraintName
    satisfied: bool
    observed: str | None
    """The product value that was compared, as a short label; never free text."""


class ScorePart(StrictModel):
    """One soft-preference component of a product's score."""

    component: ScoreComponent
    weight: Decimal
    value: Decimal
    """Between 0 and 1: how well the product satisfies this preference."""


class ScoredProduct(StrictModel):
    product_id: UUID
    score: Decimal
    """Weighted mean of the applicable parts, between 0 and 1; 0 with no parts."""
    parts: tuple[ScorePart, ...]
    checks: tuple[ConstraintCheck, ...]
    effective_price: Decimal


class SearchResults(StrictModel):
    """One deterministic page of matches plus why the rest were excluded."""

    items: tuple[ScoredProduct, ...]
    limit: int
    has_more: bool
    candidate_count: int
    """Products examined."""
    match_count: int
    """Products that satisfied every hard constraint."""
    rejections: tuple[tuple[ConstraintName, int], ...]
    """How many products each constraint excluded, for alternatives later."""
    schema_version: Literal[1]
