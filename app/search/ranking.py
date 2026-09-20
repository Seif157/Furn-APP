"""Transparent soft-preference scoring (Phase 4D).

The score is a weighted mean of independent components, each between 0 and 1,
computed only for preferences the caller actually expressed. A product with no
applicable component scores 0. Nothing here is learned or probabilistic; every
number can be recomputed by hand from the product and the specification.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from app.catalog.normalization import (
    FEELS,
    ROOM_TYPES,
    STYLES,
    NormalizedProduct,
    Vocabulary,
)
from app.personalization.profile import TasteProfile
from app.search.models import QueryText, SoftPreferences
from app.search.results import ScorePart

WEIGHTS: dict[str, Decimal] = {
    "colours": Decimal("2"),
    "materials": Decimal("2"),
    "styles": Decimal("1.5"),
    "feels": Decimal("1.25"),
    "room_type": Decimal("1"),
    "width": Decimal("1"),
    "height": Decimal("1"),
    "depth": Decimal("1"),
    "price": Decimal("1.5"),
    "query": Decimal("1"),
    # A tie-breaker, and nothing more. What someone bought last year must never
    # outweigh what they asked for today; see app/personalization/profile.py.
    "taste": Decimal("0.5"),
}
PRECISION = Decimal("0.0001")
WORD = re.compile(r"[^\W_]+")
ZERO = Decimal("0")
ONE = Decimal("1")
# Attribute kinds whose confirmed values are compared with the preference.
ROOM_KINDS = frozenset({"room", "room_type", "room type"})
STYLE_KINDS = frozenset({"style", "styles", "design_style"})
FEEL_KINDS = frozenset({"feel", "feels", "mood"})

SOFT_DIMENSIONS = {
    "styles": (STYLE_KINDS, "style", STYLES),
    "feels": (FEEL_KINDS, "feel", FEELS),
    "room_type": (ROOM_KINDS, "room_type", ROOM_TYPES),
}
"""The three dimensions no seller states: confirmed kinds, tag kind, vocabulary.

Ranking and the explanations read the same table, so a product can never be
ranked for a style the customer is not told about, or told about one that did
not count."""

INFERRED_CEILING = Decimal("0.8")
"""The most an inferred tag can contribute.

A style the seller confirmed scores 1. A style the platform guessed scores its
confidence, capped below 1, so a product whose seller said "modern" always
outranks one we merely think looks modern. The customer sees which is which in
the reasons; the arithmetic agrees with what they are told.
"""


def dimension_strengths(
    product: NormalizedProduct,
    *,
    confirmed_kinds: frozenset[str],
    tag_kind: str,
    vocabulary: Vocabulary,
) -> dict[str, Decimal]:
    """How strongly a product carries each slug of one soft dimension.

    Confirmed enrichment resolves through the same vocabulary as the query, so
    a seller who wrote "مودرن" and a customer who typed "modern" meet.
    """

    strengths: dict[str, Decimal] = {}
    for attribute in product.attributes:
        if attribute.kind not in confirmed_kinds:
            continue
        term = vocabulary.lookup(attribute.value_original)
        if term is not None:
            strengths[term.slug] = ONE
    for tag in product.tags:
        if tag.kind != tag_kind:
            continue
        value = min(tag.confidence, INFERRED_CEILING)
        if strengths.get(tag.slug, ZERO) < value:
            strengths[tag.slug] = value
    return strengths


def _preference_value(
    strengths: dict[str, Decimal], wanted: tuple[str, ...]
) -> Decimal:
    """Mean strength across everything asked for; a missing slug counts zero."""

    if not wanted:
        return ZERO
    total = sum((strengths.get(slug, ZERO) for slug in wanted), ZERO)
    return (total / Decimal(len(wanted))).quantize(PRECISION, rounding=ROUND_HALF_UP)


def _fraction(hits: int, total: int) -> Decimal:
    if total == 0:
        return ZERO
    return (Decimal(hits) / Decimal(total)).quantize(PRECISION, rounding=ROUND_HALF_UP)


def _closeness(actual: Decimal | None, target: Decimal) -> Decimal | None:
    """1 at the target, falling linearly to 0 at 100 percent deviation."""

    if actual is None:
        return None
    deviation = abs(actual - target) / target
    return max(ZERO, ONE - min(ONE, deviation)).quantize(
        PRECISION, rounding=ROUND_HALF_UP
    )


# Words that say nothing about a product, in their normalized form (Arabic
# letters folded as ``normalize_text`` folds them). Found live on 2026-09-18:
# "13000 in total" let a leather sofa tie with the modern one the customer
# asked for, because its description happened to contain "in". Only the
# customer's side is filtered; product text is left exactly as it is.
QUERY_STOPWORDS = frozenset(
    {
        # English function words and request vocabulary.
        "an",
        "the",
        "and",
        "or",
        "for",
        "in",
        "on",
        "of",
        "with",
        "to",
        "at",
        "by",
        "from",
        "me",
        "my",
        "we",
        "our",
        "need",
        "want",
        "would",
        "like",
        "looking",
        "some",
        "any",
        "under",
        "over",
        "less",
        "than",
        "more",
        "about",
        "around",
        "up",
        "is",
        "are",
        "be",
        "it",
        "that",
        "this",
        "please",
        "total",
        "budget",
        "each",
        "egp",
        "le",
        "pounds",
        "pound",
        "maximum",
        "max",
        "most",
        "least",
        "not",
        "no",
        "but",
        "just",
        "only",
        # Egyptian Arabic function words and request vocabulary, normalized.
        "في",
        "من",
        "علي",
        "الي",
        "عن",
        "مع",
        "او",
        "لو",
        "كل",
        "كده",
        "عايز",
        "عاوز",
        "عايزه",
        "محتاج",
        "محتاجه",
        "نفسي",
        "انا",
        "احنا",
        "اللي",
        "ده",
        "دي",
        "دا",
        "فيها",
        "فيه",
        "بس",
        "كام",
        "حدود",
        "ميزانيه",
        "اقل",
        "اكتر",
        "اقصي",
        "حد",
        "الف",
        "جنيه",
        "للواحد",
        "بتاع",
        "بتاعه",
        "حوالي",
        "تقريبا",
    }
)


def _tokens(text: str) -> list[str]:
    """Unicode word tokens; punctuation and separators are dropped."""

    return [token for token in WORD.findall(text) if len(token) > 1]


def _query_tokens(query: QueryText) -> list[str]:
    return [t for t in _tokens(query.normalized) if t not in QUERY_STOPWORDS]


def _haystack(product: NormalizedProduct) -> set[str]:
    haystack = set(product.search_terms)
    haystack.update(_tokens(product.name.normalized))
    if product.description is not None:
        haystack.update(_tokens(product.description.normalized))
    for term in product.search_terms:
        haystack.update(_tokens(term))
    return haystack


def _query_overlap(product: NormalizedProduct, query: QueryText) -> Decimal:
    tokens = _query_tokens(query)
    if not tokens:
        return ZERO
    haystack = _haystack(product)
    hits = sum(1 for token in tokens if token in haystack)
    return _fraction(hits, len(tokens))


def matched_query_words(
    product: NormalizedProduct, query: QueryText
) -> tuple[str, ...]:
    """The customer's own words this product's catalogue text contains.

    The same matching the query score component uses, exposed so an
    explanation can name the words rather than cite a number.
    """

    haystack = _haystack(product)
    return tuple(
        dict.fromkeys(token for token in _query_tokens(query) if token in haystack)
    )


def _taste_value(product: NormalizedProduct, profile: TasteProfile) -> Decimal | None:
    """How much this product looks like what the customer has bought before.

    Only the dimensions the profile actually has an opinion about count, so a
    customer whose history says nothing about materials is not penalised on
    them.
    """

    signals: list[Decimal] = []
    if profile.colours:
        in_stock = {c.slug for c in product.colours if c.stock_quantity > 0 and c.slug}
        signals.append(ONE if in_stock & profile.colours else ZERO)
    if profile.materials:
        present = {m.slug for m in product.materials if m.slug}
        signals.append(ONE if present & profile.materials else ZERO)
    if profile.typical_price is not None and profile.typical_price > ZERO:
        closeness = _closeness(product.effective_price, profile.typical_price)
        if closeness is not None:
            signals.append(closeness)
    if not signals:
        return None
    return (sum(signals, ZERO) / Decimal(len(signals))).quantize(
        PRECISION, rounding=ROUND_HALF_UP
    )


def score_parts(
    product: NormalizedProduct,
    soft: SoftPreferences,
    query: QueryText | None,
    profile: TasteProfile | None = None,
) -> tuple[ScorePart, ...]:
    parts: list[ScorePart] = []

    def add(component: str, value: Decimal | None) -> None:
        if value is not None:
            parts.append(
                ScorePart(
                    component=component,  # type: ignore[arg-type]
                    weight=WEIGHTS[component],
                    value=value,
                )
            )

    if soft.colours:
        in_stock = {c.slug for c in product.colours if c.stock_quantity > 0 and c.slug}
        add("colours", ONE if in_stock & set(soft.colours) else ZERO)
    if soft.materials:
        present = {m.slug for m in product.materials if m.slug}
        add(
            "materials",
            _fraction(len(present & set(soft.materials)), len(soft.materials)),
        )
    if soft.styles:
        add(
            "styles",
            _preference_value(
                dimension_strengths(
                    product,
                    confirmed_kinds=STYLE_KINDS,
                    tag_kind="style",
                    vocabulary=STYLES,
                ),
                soft.styles,
            ),
        )
    if soft.feels:
        add(
            "feels",
            _preference_value(
                dimension_strengths(
                    product,
                    confirmed_kinds=FEEL_KINDS,
                    tag_kind="feel",
                    vocabulary=FEELS,
                ),
                soft.feels,
            ),
        )
    if soft.room_type is not None:
        add(
            "room_type",
            _preference_value(
                dimension_strengths(
                    product,
                    confirmed_kinds=ROOM_KINDS,
                    tag_kind="room_type",
                    vocabulary=ROOM_TYPES,
                ),
                (soft.room_type,),
            ),
        )
    if soft.preferred_width_cm is not None:
        add("width", _closeness(product.width_cm, soft.preferred_width_cm))
    if soft.preferred_height_cm is not None:
        add("height", _closeness(product.height_cm, soft.preferred_height_cm))
    if soft.preferred_depth_cm is not None:
        add("depth", _closeness(product.depth_cm, soft.preferred_depth_cm))
    if soft.target_price is not None:
        add("price", _closeness(product.effective_price, soft.target_price))
    if query is not None:
        add("query", _query_overlap(product, query))
    if profile is not None and profile.is_useful:
        add("taste", _taste_value(product, profile))
    return tuple(parts)


def combine(parts: tuple[ScorePart, ...]) -> Decimal:
    """Weighted mean of the parts, or 0 when no preference applied."""

    total_weight = sum((part.weight for part in parts), ZERO)
    if total_weight == ZERO:
        return ZERO
    weighted = sum((part.weight * part.value for part in parts), ZERO)
    return (weighted / total_weight).quantize(PRECISION, rounding=ROUND_HALF_UP)
