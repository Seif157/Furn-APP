"""Read a customer's problem and point at the services that fit it.

"باب الدولاب اتكسر" is not a search: nothing in the catalogue answers it. It is
a service request, and the only hard part is deciding which of the marketplace's
own services it is.

The model chooses, and it chooses by position. The draft carries a number into
the list the backend sent, never a service id, a name, or a price, so the worst
a wrong answer can do is point at a different real service or at nothing. An
invented service has no way to exist: the backend resolves every number back to
the row it sent and drops anything out of range.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.provider import AIProvider, AIResponseInvalidError
from app.ai.service import conversation
from app.intake.gateway import ServiceType

MAX_CHOICES = 3
MAX_QUESTION_LENGTH = 300
MIN_CONFIDENCE = Decimal("0.3")
"""Below this the suggestion is noise, and a wrong service sends a technician
to the wrong job."""


class ServiceChoice(BaseModel):
    """One position in the list the backend sent, and how sure the model is."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    number: int | None = None
    confidence: Decimal | None = None


class TriageDraft(BaseModel):
    """What the provider answered, before any of it is believed."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    choices: Annotated[tuple[ServiceChoice, ...], Field(max_length=MAX_CHOICES)] = ()
    clarification_question: (
        Annotated[str, Field(max_length=MAX_QUESTION_LENGTH)] | None
    ) = None


@dataclass(frozen=True, slots=True)
class MatchedService:
    service: ServiceType
    confidence: Decimal


@dataclass(frozen=True, slots=True)
class Triage:
    services: tuple[MatchedService, ...]
    clarification: str | None


TRIAGE_INSTRUCTION = """\
You route a customer's request to the right service in an Egyptian furniture
marketplace. Customers write in Arabic, in English, or in a mix of both.

The prompt contains a numbered list of the services this marketplace offers,
followed by the customer's own words. Answer with the numbers of the services
that fit, most fitting first, at most three.

  Only numbers from the list. There is no other service. If nothing in the
  list fits, answer with no numbers at all; that is a correct answer and the
  customer will be told the marketplace does not offer it.

  Every one of these services is about furniture and nothing else. If the
  thing the customer describes is not a piece of furniture - a washing
  machine, a fridge, a car, plumbing, electrics, a phone, a wall - then no
  service in the list fits, however well a service's name seems to match the
  word they used. Answer with no numbers. Measured on 2026-09-20: "عايز حد
  يصلح الغسالة" matched a service called "Repair" at 0.95 because the name
  alone says nothing about furniture.

  Give each number a confidence between 0 and 1. Be honest: a request that
  could be two different services should say so with two middling numbers
  rather than one confident one.

  Ask a clarification question only when the words could mean two services and
  a single detail would decide it. Write it in the customer's own language: if
  their words contain any Arabic, write Egyptian Arabic. Otherwise English.
  Otherwise leave it null.

You never name a price, a technician, a date, or a service that is not in the
list. You return numbers and, at most, one question.
"""

TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "choices": {
            "type": "ARRAY",
            "maxItems": MAX_CHOICES,
            "items": {
                "type": "OBJECT",
                "properties": {
                    "number": {"type": "INTEGER"},
                    "confidence": {"type": "NUMBER"},
                },
                "propertyOrdering": ["number", "confidence"],
            },
        },
        "clarification_question": {
            "type": "STRING",
            "nullable": True,
            "maxLength": MAX_QUESTION_LENGTH,
        },
    },
    "propertyOrdering": list(TriageDraft.model_fields),
}


def triage_prompt(services: Sequence[ServiceType], description: str) -> str:
    """Put the real services and the customer's words in one prompt.

    Both are data rather than instruction: the service names are seller-side
    marketplace text and the description is the customer's, and neither may
    change the rules the instruction sets.
    """

    lines = ["Services:"]
    for position, service in enumerate(services, start=1):
        entry = f"{position}. {service.name}"
        if service.description:
            entry += f" - {service.description}"
        lines.append(entry)
    lines.append("")
    lines.append("Customer:")
    lines.append(description)
    return "\n".join(lines)


def services_from_draft(
    draft: TriageDraft, services: Sequence[ServiceType]
) -> tuple[MatchedService, ...]:
    """Resolve positions back to the real rows, dropping everything else."""

    matched: list[MatchedService] = []
    seen: set[int] = set()
    for choice in draft.choices:
        if choice.number is None or choice.confidence is None:
            continue
        index = choice.number - 1
        if index < 0 or index >= len(services) or index in seen:
            continue
        confidence = choice.confidence
        if not confidence.is_finite() or confidence <= 0 or confidence > 1:
            continue
        rounded = confidence.quantize(Decimal("0.01"))
        if rounded < MIN_CONFIDENCE:
            continue
        seen.add(index)
        matched.append(MatchedService(service=services[index], confidence=rounded))
    return tuple(matched)


async def triage_request(
    description: str,
    *,
    services: Sequence[ServiceType],
    provider: AIProvider,
    history: Sequence[str] = (),
) -> Triage:
    """Match one described problem to real services. Raises the parser errors."""

    turn = conversation(TRIAGE_INSTRUCTION, description, history)
    raw = await provider.generate_json(
        instruction=turn.instruction,
        prompt=triage_prompt(services, turn.prompt),
        schema=TRIAGE_SCHEMA,
    )
    try:
        draft = TriageDraft.model_validate(dict(raw))
    except ValidationError:
        raise AIResponseInvalidError from None
    question = (
        draft.clarification_question.strip() or None
        if draft.clarification_question
        else None
    )
    return Triage(services=services_from_draft(draft, services), clarification=question)
