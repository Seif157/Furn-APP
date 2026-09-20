"""Natural-language requirement parsing (Phase 5A).

The public entry point for turning one customer sentence into the same
``SearchSpecification`` a form would produce. This is the function the master
plan calls ``parse_requirements``; it lives above the provider boundary so that
every provider gets the same prompt, the same schema, and the same guardrails.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from app.ai.guardrails import RequirementDraftError, specification_from_draft
from app.ai.models import ParsedRequirements, RequirementDraft
from app.ai.prompts.requirements import REQUIREMENT_INSTRUCTION, REQUIREMENT_SCHEMA
from app.ai.provider import AIProvider
from app.search.models import DEFAULT_RESULTS, MAX_TEXT_LENGTH

REFINEMENT_SEPARATOR = " ... "

MAX_HISTORY = 4
"""Earlier messages a refinement may carry. Enough for "a sofa", "modern",
"under 30k", "in grey"; bounded so one request cannot become an essay."""

REFINEMENT_NOTE = """

This is a conversation. The prompt is the customer's messages in order, oldest
first, separated by " ... "; the last one is the latest. Return one set of
requirements for what the customer wants now. Read every phrase exactly as you
would if the customer had written all the messages as one sentence: a short
follow-up such as "في حدود ١٥ ألف" or "under 15000" means what it would mean
inside that sentence, not something weaker. "في حدود" followed by an amount is
a budget limit (max_price), exactly as in a single sentence. When the latest
message changes something said earlier, the latest message wins. Anything the
latest message does not mention stays as it was said earlier. If the latest
message starts a different search, for a different kind of furniture, use
only the latest message. Relative words
such as "cheaper", "bigger", or "أرخص" are not numbers: never invent a budget
or a size from them, and never drop one either. After "cheaper", an earlier
"under 25,000" is still max_price 25000. Only an explicit new number, or words
like "any price" or "مش مهم السعر", change or remove an earlier limit."""
"""Appended to an instruction only when there is history.

It is fixed text. The customer's messages always travel in the prompt, never in
the instruction, and a request without history sends exactly the instruction
and prompt it always did, so the measured single-sentence behaviour is
untouched.
"""


class InvalidQueryError(ValueError):
    """Raised when the caller's text cannot be searched for at all."""


def validate_query(text: str) -> str:
    """Return the sentence to parse, or refuse it before spending a call."""

    stripped = text.strip()
    if not stripped:
        raise InvalidQueryError("a search query cannot be empty")
    if len(stripped) > MAX_TEXT_LENGTH:
        raise InvalidQueryError(
            f"a search query cannot exceed {MAX_TEXT_LENGTH} characters"
        )
    return stripped


@dataclass(frozen=True, slots=True)
class Conversation:
    """What one turn sends to the model, and the words ranking scores."""

    instruction: str
    prompt: str
    query: str
    """The text ranking scores and language is detected from: the latest
    message plus as many earlier ones as fit in ``MAX_TEXT_LENGTH``, newest
    kept first, so words said earlier ("modern") still count."""


def conversation(
    base_instruction: str, latest: str, history: Sequence[str] = ()
) -> Conversation:
    """Validate a turn and shape it for the model. Raises InvalidQueryError."""

    message = validate_query(latest)
    if len(history) > MAX_HISTORY:
        raise InvalidQueryError(f"at most {MAX_HISTORY} earlier messages")
    earlier = [validate_query(item) for item in history]
    if not earlier:
        return Conversation(base_instruction, message, message)

    # One continuous sentence, in order. Measured live on 2026-09-18 against
    # labelled "Earlier message 1:" lines: 24/24 against 23/24, and a short
    # follow-up such as "في حدود ١٥ ألف" then reads as the limit it is in a
    # single sentence rather than as a weaker preference.
    prompt = REFINEMENT_SEPARATOR.join(
        " ".join(text.split()) for text in [*earlier, message]
    )

    kept = [message]
    for text in reversed(earlier):
        candidate = " ".join([text, *kept])
        if len(candidate) > MAX_TEXT_LENGTH:
            break
        kept.insert(0, text)
    return Conversation(
        instruction=base_instruction + REFINEMENT_NOTE,
        prompt=prompt,
        query=" ".join(kept),
    )


async def parse_requirements(
    text: str,
    *,
    provider: AIProvider,
    limit: int = DEFAULT_RESULTS,
    history: Sequence[str] = (),
) -> ParsedRequirements:
    """Parse one sentence into a validated specification.

    Raises ``InvalidQueryError`` for unusable input, ``AIProviderUnavailableError``
    when the provider could not answer, and ``AIResponseInvalidError`` when it
    answered with something that cannot be trusted. It never returns a
    specification containing a value the vocabularies and bounds did not accept.
    """

    turn = conversation(REQUIREMENT_INSTRUCTION, text, history)

    raw = await provider.generate_json(
        instruction=turn.instruction,
        prompt=turn.prompt,
        schema=REQUIREMENT_SCHEMA,
    )

    try:
        draft = RequirementDraft.model_validate(dict(raw))
    except ValidationError:
        raise RequirementDraftError from None

    build = specification_from_draft(draft, query=turn.query, limit=limit)
    clarification = (
        draft.clarification_question.strip() or None
        if draft.clarification_question
        else None
    )
    return ParsedRequirements(
        specification=build.specification,
        unresolved=build.unresolved,
        clarification=clarification,
    )
