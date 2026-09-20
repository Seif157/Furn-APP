"""Infer a product's style, room and feel from its own catalogue entry.

This is the only place the platform forms an opinion about a product. It runs
offline, per product, never in a request, and its output is written to
``product_search_tag`` where its provenance is a column.

Two guarantees, both structural rather than asked for in the prompt. The draft
has no field that can carry a marketplace fact, so a model that invents a price
or a seller has nowhere to put it. And a term that is not already in the
vocabulary is dropped, never added, so the words search can match are decided
by this codebase and not by a generated answer.

A guess is allowed to be wrong. It may only ever change the order of results,
and the customer is told which statements are guesses; see
app/recommendations/explanations.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.provider import AIProvider, AIResponseInvalidError, ImageBytes
from app.catalog.normalization import (
    FEELS,
    ROOM_TYPES,
    STYLES,
    InferredTag,
    TagKind,
    Vocabulary,
    VocabularyTerm,
)

MAX_SURFACE_LENGTH = 80
MAX_GUESSES = 6
"""Per list, before filtering. The model is asked for three."""

MAX_TAGS_PER_KIND = 3
"""Kept per kind after filtering. A product that is everything is nothing."""

MIN_CONFIDENCE = Decimal("0.4")
"""Below this a guess is not worth storing: it cannot lift a product far and
it can still be wrong in a way a customer reads as a claim."""

TAG_LISTS: tuple[tuple[str, TagKind, Vocabulary], ...] = (
    ("styles", "style", STYLES),
    ("rooms", "room_type", ROOM_TYPES),
    ("feels", "feel", FEELS),
)


class TagGuess(BaseModel):
    """One suggested word and how sure the model says it is."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    term: Annotated[str, Field(max_length=MAX_SURFACE_LENGTH)] = ""
    confidence: Decimal | None = None


GuessList = Annotated[tuple[TagGuess, ...], Field(max_length=MAX_GUESSES)]


class TagDraft(BaseModel):
    """What the provider answered, before any of it is believed."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    styles: GuessList = ()
    rooms: GuessList = ()
    feels: GuessList = ()


def _confidence(value: Decimal | None) -> Decimal | None:
    """Keep a usable confidence, rounded to the two decimals the table stores."""

    if value is None:
        return None
    try:
        if not value.is_finite() or value <= 0 or value > 1:
            return None
        quantized = value.quantize(Decimal("0.01"))
    except (ArithmeticError, InvalidOperation):
        return None
    if quantized < MIN_CONFIDENCE:
        return None
    return quantized


def _resolve(vocabulary: Vocabulary, term: str) -> VocabularyTerm | None:
    """Accept the slug the instruction asks for, or the word a model preferred.

    The prompt asks for slugs, and a model that answers "living room" or
    "مودرن" instead is right about the product and wrong about the format.
    Both are resolved; anything outside the vocabulary is still dropped.
    """

    stripped = term.strip()
    if not stripped:
        return None
    try:
        return vocabulary.term(stripped.lower())
    except KeyError:
        return vocabulary.lookup(stripped)


def tags_from_draft(draft: TagDraft) -> tuple[InferredTag, ...]:
    """Resolve a draft into tags this build can actually match on.

    Everything unrecognised is dropped rather than repaired: the vocabulary is
    the contract between what a customer can type and what a tag can say, and
    widening it from a generated answer would break that in the one direction
    nobody would notice.
    """

    tags: list[InferredTag] = []
    for field, kind, vocabulary in TAG_LISTS:
        best: dict[str, Decimal] = {}
        for guess in getattr(draft, field):
            term = _resolve(vocabulary, guess.term)
            confidence = _confidence(guess.confidence)
            if term is None or confidence is None:
                continue
            if best.get(term.slug, Decimal("0")) < confidence:
                best[term.slug] = confidence
        ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))
        tags.extend(
            InferredTag(kind=kind, slug=slug, confidence=confidence)
            for slug, confidence in ranked[:MAX_TAGS_PER_KIND]
        )
    return tuple(tags)


def _vocabulary_lines(vocabulary: Vocabulary) -> str:
    return "\n".join(f"  {term.slug}: {term.english}" for term in vocabulary.terms)


TAGGING_INSTRUCTION = f"""\
You label furniture for an Egyptian marketplace's search engine.

You are given one product's own catalogue entry, and sometimes a photograph of
it. Say which of the listed styles, rooms and feels the product fits. Answer
with the slug on the left, never with your own wording.

Styles, how the piece looks:
{_vocabulary_lines(STYLES)}

Rooms, where this piece belongs:
{_vocabulary_lines(ROOM_TYPES)}

Feels, what a room with this piece in it would feel like:
{_vocabulary_lines(FEELS)}

Rules.

  Answer with at most three entries per list, the ones you are most sure of.
  An empty list is a correct answer. Say nothing rather than guess wildly.

  Give each entry a confidence between 0 and 1: how sure you are that a
  customer searching that word would be happy to be shown this product. Use
  the whole range honestly. Anything below 0.4 is discarded, so a weak hunch
  costs you nothing to leave out.

  Judge only the piece itself. A sofa is not "cosy" because the photograph has
  a blanket in it, and it is not "luxury" because it is expensive; you are not
  told the price and must not infer one.

  A room means where this piece would normally go, not every room it could
  physically fit in.

You are labelling, not describing. Do not write a product name, a price, a
material list, a size, a seller, or any sentence at all: the only words you
return are slugs from the lists above.
"""


_GUESS_LIST: dict[str, Any] = {
    "type": "ARRAY",
    "maxItems": MAX_GUESSES,
    "items": {
        "type": "OBJECT",
        "properties": {
            "term": {"type": "STRING", "maxLength": MAX_SURFACE_LENGTH},
            "confidence": {"type": "NUMBER"},
        },
        "propertyOrdering": ["term", "confidence"],
    },
}

TAGGING_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "styles": _GUESS_LIST,
        "rooms": _GUESS_LIST,
        "feels": _GUESS_LIST,
    },
    "propertyOrdering": list(TagDraft.model_fields),
}


def product_prompt(
    *,
    name: str,
    description: str | None,
    category: str,
    materials: Sequence[str] = (),
    colours: Sequence[str] = (),
) -> str:
    """Describe one product to the model, in the seller's own words.

    Seller text is not backend text, so it travels in the prompt and never in
    the instruction, exactly as a customer's sentence does.
    """

    lines = [f"Category: {category}", f"Name: {name}"]
    if description:
        lines.append(f"Description: {description}")
    if materials:
        lines.append("Materials: " + ", ".join(materials))
    if colours:
        lines.append("Colours: " + ", ".join(colours))
    return "\n".join(lines)


async def infer_tags(
    prompt: str,
    *,
    provider: AIProvider,
    photographs: Sequence[ImageBytes] = (),
) -> tuple[InferredTag, ...]:
    """Ask for one product's tags and return only the believable ones.

    Raises the provider's own errors. An answer that is not the expected shape
    raises ``AIResponseInvalidError``; an answer with nothing usable in it is
    an empty tuple, which is a valid outcome and not an error.
    """

    raw = await provider.generate_json(
        instruction=TAGGING_INSTRUCTION,
        prompt=prompt,
        schema=TAGGING_SCHEMA,
        references=photographs,
    )
    try:
        draft = TagDraft.model_validate(dict(raw))
    except ValidationError:
        raise AIResponseInvalidError from None
    return tags_from_draft(draft)
