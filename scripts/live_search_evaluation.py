"""Run the Phase 5D benchmark against a real provider and report the numbers.

One provider call per case, so it costs money and needs an explicit decision:

    uv run python -m scripts.live_search_evaluation --i-have-authorization

The catalogue is the Phase 5 seed fixture, not Supabase, so the retrieval half
is identical every run and any movement in the numbers comes from the model.
Nothing is written anywhere.

Add --repeat N to measure stability rather than a single sample. A model at
temperature zero is still not deterministic, and a benchmark run once reports
luck as accuracy.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import NoReturn

import httpx

from app.ai.provider import AIProviderError
from app.ai.providers.gemini import build_gemini_provider
from app.ai.service import parse_requirements
from app.config import load_ai_settings
from tests import evaluation as ev

AUTHORIZATION_FLAG = "--i-have-authorization"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure natural-language search against the Phase 5D cases."
    )
    parser.add_argument(AUTHORIZATION_FLAG, action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--verbose", action="store_true", help="Show every field.")
    return parser.parse_args()


async def run(*, repeat: int, verbose: bool) -> int:
    settings = load_ai_settings()
    if not settings.gemini_enabled:
        print("no GEMINI_API_KEY configured", file=sys.stderr)
        return 2

    catalogue = ev.eligible_catalogue()
    print(f"model:     {settings.gemini_model}")
    print(f"catalogue: {len(catalogue)} eligible seed products")
    print(f"cases:     {len(ev.CASES)} x {repeat}\n")

    outcomes: list[ev.CaseOutcome] = []
    errors = 0

    async with httpx.AsyncClient() as client:
        provider = build_gemini_provider(client=client, settings=settings)
        assert provider is not None
        for attempt in range(repeat):
            for case in ev.CASES:
                try:
                    parsed = await parse_requirements(case.query, provider=provider)
                except AIProviderError as error:
                    # A transient upstream failure is not a wrong answer, so it
                    # is counted separately rather than scored as one.
                    errors += 1
                    print(f"  ERROR {case.name}: {type(error).__name__}")
                    continue

                outcome = ev.evaluate_case(
                    case,
                    parsed.specification,
                    catalogue=catalogue,
                    clarification=parsed.clarification,
                    unresolved=tuple(term.surface for term in parsed.unresolved),
                )
                outcomes.append(outcome)

                flags = []
                if not outcome.extraction_correct:
                    flags.append("EXTRACTION")
                if outcome.violations:
                    flags.append("VIOLATION")
                if outcome.hallucinated:
                    flags.append("HALLUCINATION")
                if not outcome.clarification_correct:
                    flags.append("CLARIFICATION")
                if not outcome.unresolved_correct:
                    flags.append("UNRESOLVED")

                mark = "ok  " if not flags else "FAIL"
                suffix = f"  [{' '.join(flags)}]" if flags else ""
                if repeat > 1:
                    label = f"{case.name} #{attempt + 1}"
                else:
                    label = case.name
                print(
                    f"  {mark} {label:34} recall={outcome.recall:.0%}"
                    f" returned={len(outcome.returned_ids)}"
                    f" expected={len(outcome.expected_ids)}{suffix}"
                )
                if verbose or flags:
                    for score in outcome.fields:
                        if not score.correct:
                            print(
                                f"        {score.field}: expected "
                                f"{score.expected!r}, got {score.actual!r}"
                            )

    report = ev.Report(tuple(outcomes))
    print("\n" + report.summary())
    if errors:
        print(f"provider errors:          {errors} (not scored)")

    # The one number the master plan puts a target on.
    if report.hallucination_rate > 0:
        print("\nFAILED: hallucination rate must be zero", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    arguments = parse_arguments()
    if not arguments.i_have_authorization:
        print(
            f"refusing: this spends one provider call per case. Re-run with "
            f"{AUTHORIZATION_FLAG} if you intend that.",
            file=sys.stderr,
        )
        return 2
    if arguments.repeat < 1:
        print("refusing: --repeat must be at least 1", file=sys.stderr)
        return 2
    try:
        return asyncio.run(run(repeat=arguments.repeat, verbose=arguments.verbose))
    except KeyboardInterrupt:
        return 130


def _exit() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _exit()
