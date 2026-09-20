"""Measure the three new prompts against the live model. Run it yourself.

    uv run python -m scripts.live_intake_smoke --i-have-authorization
    uv run python -m scripts.live_intake_smoke --i-have-authorization --repeats 3

Tagging, service triage and the furnishing brief were all written and tested
against a stub. This is the first thing that puts them in front of Gemini, the
way scripts/live_gemini_smoke.py and the Phase 5D evaluation did for search.

It contacts Google and nothing else: no Supabase, no sign-in, no writes. The
products come from the offline seed, and the service list is a plausible
directory written here, because reading the real one needs a signed-in session.
That is enough to measure what these prompts get wrong, which is whether they
choose from the list they were given, refuse when they should, and keep their
hands off marketplace facts.

Each case states what a correct answer looks like. A case that fails prints why.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

import httpx
from pydantic import TypeAdapter

from app.ai.provider import AIProvider, AIProviderError
from app.ai.providers.gemini import build_gemini_provider
from app.ai.tagging import consensus, infer_tags, product_prompt
from app.catalog.normalization import InferredTag
from app.catalog.upstream_models import UpstreamProduct
from app.config import load_ai_settings
from app.intake.brief import read_brief
from app.intake.gateway import ServiceType
from app.intake.triage import triage_request
from tests import seed_catalogue as seed

SERVICES = (
    ServiceType(
        id=uuid4(),
        name="Furniture assembly",
        description="Assemble flat-pack or delivered furniture at home",
    ),
    ServiceType(
        id=uuid4(),
        name="Repair",
        description="Fix broken doors, drawers, hinges and frames",
    ),
    ServiceType(
        id=uuid4(),
        name="Upholstery",
        description="Re-cover sofas and chairs in new fabric",
    ),
    ServiceType(
        id=uuid4(),
        name="Interior design consultation",
        description="An designer visits and plans the space",
    ),
    ServiceType(
        id=uuid4(),
        name="Moving and delivery",
        description="Move furniture between homes",
    ),
)

FAILURES: list[str] = []

# This machine's console is a Windows code page that cannot encode Arabic, and
# every case here is half Arabic. Without this the run dies mid-measurement.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def check(condition: bool, label: str, detail: str = "") -> None:
    print(
        ("  ok    " if condition else "  FAIL  ")
        + label
        + (f"  [{detail}]" if detail and not condition else "")
    )
    if not condition:
        FAILURES.append(label)


@dataclass(frozen=True, slots=True)
class TriageCase:
    description: str
    expected: str | None
    """The service name that must come first, or None when nothing should match."""


TRIAGE_CASES = (
    TriageCase("باب الدولاب اتكسر", "Repair"),
    TriageCase("I need someone to put my new wardrobe together", "Furniture assembly"),
    TriageCase("الكنبة قماشها قديم عايز أغيره", "Upholstery"),
    TriageCase("محتاج حد ينقل عفشي لشقة جديدة", "Moving and delivery"),
    # Nothing in the directory does this. The right answer is no answer.
    TriageCase("عايز حد يصلح الغسالة", None),
)

BRIEF_CASES = (
    (
        "عايز أفرش شقة فيها ٣ أوض نوم وريسبشن بميزانية ١٥٠ ألف، ستايل مودرن",
        {"bedroom": 3, "reception": 1},
        Decimal("150000"),
        ("modern",),
    ),
    (
        "furnishing a small two bedroom flat and a home office, around 90k",
        {"bedroom": 2, "home_office": 1},
        Decimal("90000"),
        (),
    ),
    # No rooms, no budget: the one case that should ask a question.
    ("عايز أجدد البيت", {}, None, ()),
)


def summarise(tags: tuple[InferredTag, ...]) -> str:
    return ", ".join(f"{tag.kind}:{tag.slug}" for tag in tags) or "-"


def seed_products() -> tuple[UpstreamProduct, ...]:
    products = TypeAdapter(tuple[UpstreamProduct, ...]).validate_json(
        seed.as_json_fixture()
    )
    return products


async def run_tagging(provider: AIProvider, repeats: int) -> None:
    print("\ntagging: does it label real products with vocabulary slugs only?")
    products = seed_products()[:4]
    for product in products:
        prompt = product_prompt(
            name=product.name,
            description=product.description,
            category=product.category.name,
            materials=product.materials,
            colours=tuple(colour.color_value for colour in product.colors),
        )
        seen: list[tuple[InferredTag, ...]] = []
        for _ in range(repeats * 2):
            try:
                seen.append(await infer_tags(prompt, provider=provider))
            except AIProviderError as error:
                check(False, f"{product.name}: answered", type(error).__name__)
                break
        else:
            raw = [
                ", ".join(f"{tag.kind}:{tag.slug}" for tag in tags) or "-"
                for tags in seen
            ]
            # What one call says is not what gets written: the derivation
            # script writes the consensus of several runs, so that is what has
            # to hold still.
            #
            # Measured on 2026-09-20 over 6 runs per product: style and room
            # are identical every time, and the third feel rotates among two
            # or three equally defensible ones ("cosy" or "hotel-like" for the
            # same wooden bed). So style and room are required to agree, and a
            # differing feel is reported rather than failed: it is a guess
            # worth at most 0.6 of one soft component, and demanding
            # determinism from the marginal case would mean either dropping
            # feels entirely or pretending to a precision that is not there.
            first = consensus(seen[:repeats])
            second = consensus(seen[repeats:])
            firm = {
                (tag.kind, tag.slug)
                for tag in first
                if tag.kind in ("style", "room_type")
            }
            firm_again = {
                (tag.kind, tag.slug)
                for tag in second
                if tag.kind in ("style", "room_type")
            }
            check(
                firm == firm_again,
                f"{product.name}: style and room hold still",
                f"{summarise(first)} | {summarise(second)}",
            )
            feels = {tag.slug for tag in first if tag.kind == "feel"}
            feels_again = {tag.slug for tag in second if tag.kind == "feel"}
            if feels != feels_again:
                print(f"        (feels differed: {sorted(feels ^ feels_again)})")
            if len(set(raw)) > 1:
                print(f"        (single runs varied: {len(set(raw))} of {len(raw)})")
            print(f"        {summarise(first)}")


async def run_triage(provider: AIProvider, repeats: int) -> None:
    print("\ntriage: does it pick the right real service, and refuse when none fits?")
    for case in TRIAGE_CASES:
        answers: list[str] = []
        for _ in range(repeats):
            try:
                triage = await triage_request(
                    case.description, services=SERVICES, provider=provider
                )
            except AIProviderError as error:
                check(False, f"{case.description}: answered", type(error).__name__)
                break
            answers.append(triage.services[0].service.name if triage.services else "-")
        else:
            expected = case.expected or "-"
            check(
                all(answer == expected for answer in answers),
                f"{case.description[:40]} -> {expected}",
                " | ".join(answers),
            )


async def run_brief(provider: AIProvider, repeats: int) -> None:
    print("\nbrief: does a description become the right form?")
    for description, rooms, budget, styles in BRIEF_CASES:
        for _ in range(repeats):
            try:
                brief = await read_brief(description, provider=provider)
            except AIProviderError as error:
                check(False, f"{description[:40]}: answered", type(error).__name__)
                break
            got_rooms = {room.room_type: room.quantity for room in brief.rooms}
            check(got_rooms == rooms, f"{description[:40]}: rooms", str(got_rooms))
            check(
                brief.total_budget == budget,
                f"{description[:40]}: budget",
                str(brief.total_budget),
            )
            if styles:
                check(
                    brief.styles == styles,
                    f"{description[:40]}: styles",
                    str(brief.styles),
                )
            if not rooms and budget is None:
                check(
                    brief.clarification is not None,
                    f"{description[:40]}: asks rather than invents",
                )


async def run(repeats: int) -> int:
    settings = load_ai_settings()
    async with httpx.AsyncClient() as client:
        provider = build_gemini_provider(client=client, settings=settings)
        if provider is None:
            print("refusing: no GEMINI_API_KEY is configured", file=sys.stderr)
            return 2
        print(f"model: {settings.gemini_model}, {repeats} run(s) per case")
        await run_tagging(provider, repeats)
        await run_triage(provider, repeats)
        await run_brief(provider, repeats)

    print(f"\n{'PASSED' if not FAILURES else 'FAILED'}: {len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--i-have-authorization", action="store_true")
    parser.add_argument("--repeats", type=int, default=2)
    arguments = parser.parse_args(argv)
    if not arguments.i_have_authorization:
        print(
            "refusing: pass --i-have-authorization. This spends model calls.",
            file=sys.stderr,
        )
        return 2
    return asyncio.run(run(arguments.repeats))


if __name__ == "__main__":
    raise SystemExit(main())
