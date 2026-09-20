"""Typed search specification (Phase 4C).

A ``SearchSpecification`` separates hard constraints, which a product must
satisfy, from soft preferences, which only influence ranking. Every field maps
to something the Phase 4B ``NormalizedProduct`` can answer today: category,
colour, and material slugs from the controlled vocabularies, price and
dimension ranges in the catalogue's own units, and stock. Weight is not a
constraint because the audit found it null on every product.

Style, room type and feel are slugs too, but they stay soft for a different
reason: no seller states them, so they are matched against platform-inferred
tags. A guess may order results; it may never exclude a product.

The models are strict and frozen. Slugs are validated against the vocabularies
so an unknown value is rejected at construction, never silently ignored. The
``build_specification`` helper accepts surface forms in either language and
reports what it could not resolve, which is the input for clarification.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.catalog.normalization import (
    CATEGORIES,
    COLOURS,
    FEELS,
    MATERIALS,
    ROOM_TYPES,
    STYLES,
    Vocabulary,
    has_arabic,
    has_latin,
    normalize_text,
)

MAX_RESULTS = 50
DEFAULT_RESULTS = 20
MAX_PRICE = Decimal("100000000")
MAX_DIMENSION_CM = Decimal("100000")
MAX_TERMS = 10
MAX_TEXT_LENGTH = 500

Language = Literal["ar", "en", "mixed"]
SpecificationField = Literal[
    "category",
    "colours",
    "materials",
    "preferred_colours",
    "preferred_materials",
    "styles",
    "room_type",
    "feels",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        allow_inf_nan=False, extra="forbid", frozen=True, strict=True
    )


def _in_range(
    value: Decimal, *, low: Decimal, high: Decimal, exclusive_low: bool
) -> bool:
    if not value.is_finite():
        return False
    if exclusive_low and value <= low:
        return False
    if not exclusive_low and value < low:
        return False
    return value <= high


def _validate_slugs(vocabulary: Vocabulary, slugs: tuple[str, ...]) -> tuple[str, ...]:
    if len(slugs) > MAX_TERMS:
        raise ValueError(f"at most {MAX_TERMS} {vocabulary.name} terms")
    if len(set(slugs)) != len(slugs):
        raise ValueError(f"duplicate {vocabulary.name} slug")
    for slug in slugs:
        if slug not in {term.slug for term in vocabulary.terms}:
            raise ValueError(f"unknown {vocabulary.name} slug: {slug}")
    return slugs


class PriceRange(StrictModel):
    """Inclusive price bounds in the catalogue currency."""

    minimum: Decimal | None = None
    maximum: Decimal | None = None

    @field_validator("minimum", "maximum")
    @classmethod
    def _non_negative_and_bounded(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not _in_range(
            value, low=Decimal("0"), high=MAX_PRICE, exclusive_low=False
        ):
            raise ValueError("price bound out of range")
        return value

    @model_validator(mode="after")
    def _ordered(self) -> PriceRange:
        if self.minimum is None and self.maximum is None:
            raise ValueError("a price range needs at least one bound")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("price minimum exceeds maximum")
        return self


class DimensionRange(StrictModel):
    """Inclusive bounds in centimetres, matching the catalogue columns."""

    minimum_cm: Decimal | None = None
    maximum_cm: Decimal | None = None

    @field_validator("minimum_cm", "maximum_cm")
    @classmethod
    def _positive_and_bounded(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not _in_range(
            value, low=Decimal("0"), high=MAX_DIMENSION_CM, exclusive_low=True
        ):
            raise ValueError("dimension bound out of range")
        return value

    @model_validator(mode="after")
    def _ordered(self) -> DimensionRange:
        if self.minimum_cm is None and self.maximum_cm is None:
            raise ValueError("a dimension range needs at least one bound")
        if (
            self.minimum_cm is not None
            and self.maximum_cm is not None
            and self.minimum_cm > self.maximum_cm
        ):
            raise ValueError("dimension minimum exceeds maximum")
        return self


class HardConstraints(StrictModel):
    """Conditions a product must satisfy to be a candidate at all."""

    category: str | None = None
    colours: tuple[str, ...] = ()
    """Any of these colour slugs must be in stock on the product."""
    materials: tuple[str, ...] = ()
    """All of these material slugs must be present on the product."""
    price: PriceRange | None = None
    width: DimensionRange | None = None
    height: DimensionRange | None = None
    depth: DimensionRange | None = None
    in_stock_only: bool = True

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_slugs(CATEGORIES, (value,))
        return value

    @field_validator("colours")
    @classmethod
    def _known_colours(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_slugs(COLOURS, value)

    @field_validator("materials")
    @classmethod
    def _known_materials(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_slugs(MATERIALS, value)


class SoftPreferences(StrictModel):
    """Signals that rank candidates without excluding any."""

    colours: tuple[str, ...] = ()
    materials: tuple[str, ...] = ()
    styles: tuple[str, ...] = ()
    """Style slugs, matched against confirmed enrichment and inferred tags."""
    room_type: str | None = None
    feels: tuple[str, ...] = ()
    """How the customer wants it to feel. Only inferred tags can answer these."""
    preferred_width_cm: Decimal | None = None
    preferred_height_cm: Decimal | None = None
    preferred_depth_cm: Decimal | None = None
    target_price: Decimal | None = None

    @field_validator("colours")
    @classmethod
    def _known_colours(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_slugs(COLOURS, value)

    @field_validator("materials")
    @classmethod
    def _known_materials(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_slugs(MATERIALS, value)

    @field_validator("styles")
    @classmethod
    def _known_styles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_slugs(STYLES, value)

    @field_validator("feels")
    @classmethod
    def _known_feels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_slugs(FEELS, value)

    @field_validator("room_type")
    @classmethod
    def _known_room(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_slugs(ROOM_TYPES, (value,))
        return value

    @field_validator("preferred_width_cm", "preferred_height_cm", "preferred_depth_cm")
    @classmethod
    def _positive_dimension(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not _in_range(
            value, low=Decimal("0"), high=MAX_DIMENSION_CM, exclusive_low=True
        ):
            raise ValueError("preferred dimension out of range")
        return value

    @field_validator("target_price")
    @classmethod
    def _positive_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not _in_range(
            value, low=Decimal("0"), high=MAX_PRICE, exclusive_low=True
        ):
            raise ValueError("target price out of range")
        return value


class QueryText(StrictModel):
    """The caller's original wording, kept for tracing and clarification."""

    original: str
    normalized: str
    language: Language

    @field_validator("original")
    @classmethod
    def _bounded(cls, value: str) -> str:
        if not value.strip() or len(value) > MAX_TEXT_LENGTH:
            raise ValueError("query text must be non-empty and bounded")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> QueryText:
        if self.normalized != normalize_text(self.original):
            raise ValueError("normalized text does not match original")
        if self.language != detect_language(self.original):
            raise ValueError("language does not match original")
        return self


class SearchSpecification(StrictModel):
    """The complete, validated input to structured retrieval and ranking."""

    hard: HardConstraints = HardConstraints()
    soft: SoftPreferences = SoftPreferences()
    query: QueryText | None = None
    limit: int = Field(default=DEFAULT_RESULTS, ge=1, le=MAX_RESULTS)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def _has_some_signal(self) -> SearchSpecification:
        hard = self.hard.model_dump(exclude={"in_stock_only"}, exclude_none=True)
        soft = self.soft.model_dump(exclude_none=True)
        if not any(hard.values()) and not any(soft.values()) and self.query is None:
            raise ValueError(
                "a specification needs at least one constraint or preference"
            )
        return self


def states_a_requirement(specification: SearchSpecification) -> bool:
    """True when the sentence asked for something, not merely said something.

    "عايز كنبة" states a requirement. "ما هي عاصمة فرنسا؟" does not: it parses
    into a specification whose only content is the raw text, which as a search
    means "everything". The caller uses this to answer with a question instead
    of with the whole catalogue.

    ``in_stock_only`` counts only when it is false. True is the default on
    every parse and says nothing; false is the customer saying they will wait
    or that availability does not matter, which is a statement, and "show me
    everything, in stock or not" deserves everything rather than a question.
    """

    hard = specification.hard.model_dump(exclude={"in_stock_only"}, exclude_none=True)
    soft = specification.soft.model_dump(exclude_none=True)
    return (
        any(hard.values())
        or any(soft.values())
        or specification.hard.in_stock_only is False
    )


class UnresolvedTerm(StrictModel):
    """A surface form the vocabularies could not map; input for clarification."""

    field: SpecificationField
    surface: str


class SpecificationBuild(StrictModel):
    specification: SearchSpecification
    unresolved: tuple[UnresolvedTerm, ...]


def detect_language(text: str) -> Language:
    arabic = has_arabic(text)
    latin = has_latin(text)
    if arabic and latin:
        return "mixed"
    if arabic:
        return "ar"
    return "en"


def query_text(text: str) -> QueryText:
    return QueryText(
        original=text,
        normalized=normalize_text(text),
        language=detect_language(text),
    )


def _resolve(
    vocabulary: Vocabulary,
    surfaces: Iterable[str],
    *,
    field: SpecificationField,
    unresolved: list[UnresolvedTerm],
) -> tuple[str, ...]:
    slugs: list[str] = []
    for surface in surfaces:
        term = vocabulary.lookup(surface)
        if term is None:
            unresolved.append(UnresolvedTerm(field=field, surface=surface))
        elif term.slug not in slugs:
            slugs.append(term.slug)
    return tuple(slugs)


def build_specification(
    *,
    category: str | None = None,
    colours: Iterable[str] = (),
    materials: Iterable[str] = (),
    price: PriceRange | None = None,
    width: DimensionRange | None = None,
    height: DimensionRange | None = None,
    depth: DimensionRange | None = None,
    in_stock_only: bool = True,
    preferred_colours: Iterable[str] = (),
    preferred_materials: Iterable[str] = (),
    styles: Iterable[str] = (),
    room_type: str | None = None,
    feels: Iterable[str] = (),
    preferred_width_cm: Decimal | None = None,
    preferred_height_cm: Decimal | None = None,
    preferred_depth_cm: Decimal | None = None,
    target_price: Decimal | None = None,
    query: str | None = None,
    limit: int = DEFAULT_RESULTS,
) -> SpecificationBuild:
    """Resolve surface forms in either language to slugs and build the spec.

    Unresolvable surfaces are reported, not guessed. A category that does not
    resolve leaves the category unset, so the caller can ask for clarification.
    """

    unresolved: list[UnresolvedTerm] = []
    category_slug: str | None = None
    if category is not None:
        (category_slug, *_rest) = _resolve(
            CATEGORIES, (category,), field="category", unresolved=unresolved
        ) or (None,)
    room_slug: str | None = None
    if room_type is not None:
        (room_slug, *_rest) = _resolve(
            ROOM_TYPES, (room_type,), field="room_type", unresolved=unresolved
        ) or (None,)
    specification = SearchSpecification(
        hard=HardConstraints(
            category=category_slug,
            colours=_resolve(COLOURS, colours, field="colours", unresolved=unresolved),
            materials=_resolve(
                MATERIALS, materials, field="materials", unresolved=unresolved
            ),
            price=price,
            width=width,
            height=height,
            depth=depth,
            in_stock_only=in_stock_only,
        ),
        soft=SoftPreferences(
            colours=_resolve(
                COLOURS,
                preferred_colours,
                field="preferred_colours",
                unresolved=unresolved,
            ),
            materials=_resolve(
                MATERIALS,
                preferred_materials,
                field="preferred_materials",
                unresolved=unresolved,
            ),
            styles=_resolve(STYLES, styles, field="styles", unresolved=unresolved),
            feels=_resolve(FEELS, feels, field="feels", unresolved=unresolved),
            room_type=room_slug,
            preferred_width_cm=preferred_width_cm,
            preferred_height_cm=preferred_height_cm,
            preferred_depth_cm=preferred_depth_cm,
            target_price=target_price,
        ),
        query=query_text(query) if query else None,
        limit=limit,
    )
    return SpecificationBuild(specification=specification, unresolved=tuple(unresolved))
