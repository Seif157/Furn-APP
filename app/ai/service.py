"""Natural-language requirement parsing (Phase 5A).

The public entry point for turning one customer sentence into the same
``SearchSpecification`` a form would produce. This is the function the master
plan calls ``parse_requirements``; it lives above the provider boundary so that
every provider gets the same prompt, the same schema, and the same guardrails.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.ai.guardrails import RequirementDraftError, specification_from_draft
from app.ai.models import ParsedRequirements, RequirementDraft
from app.ai.prompts.requirements import REQUIREMENT_INSTRUCTION, REQUIREMENT_SCHEMA
from app.ai.provider import AIProvider
from app.search.models import DEFAULT_RESULTS, MAX_TEXT_LENGTH


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


async def parse_requirements(
    text: str,
    *,
    provider: AIProvider,
    limit: int = DEFAULT_RESULTS,
) -> ParsedRequirements:
    """Parse one sentence into a validated specification.

    Raises ``InvalidQueryError`` for unusable input, ``AIProviderUnavailableError``
    when the provider could not answer, and ``AIResponseInvalidError`` when it
    answered with something that cannot be trusted. It never returns a
    specification containing a value the vocabularies and bounds did not accept.
    """

    query = validate_query(text)

    raw = await provider.generate_json(
        instruction=REQUIREMENT_INSTRUCTION,
        prompt=query,
        schema=REQUIREMENT_SCHEMA,
    )

    try:
        draft = RequirementDraft.model_validate(dict(raw))
    except ValidationError:
        raise RequirementDraftError from None

    build = specification_from_draft(draft, query=query, limit=limit)
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
