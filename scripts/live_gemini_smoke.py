"""Send exactly one live Gemini request and print the specification it yields.

This is the only code in the repository that contacts an AI provider. Nothing
in the test suite or the tooling runs it. It spends money, leaves the sentence
in a provider's logs, and therefore needs a human decision every time:

    uv run python -m scripts.live_gemini_smoke --i-have-authorization "<sentence>"

The key is read from GEMINI_API_KEY or prompted for without echo, and is never
printed, logged, or written anywhere. One sentence in, one request out.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from typing import NoReturn

import httpx

from app.ai.provider import AIProviderError
from app.ai.providers.gemini import GeminiProvider
from app.ai.service import InvalidQueryError, parse_requirements, validate_query
from app.config import AISettings, load_ai_settings

AUTHORIZATION_FLAG = "--i-have-authorization"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One live Gemini requirement-extraction call.",
    )
    parser.add_argument(
        AUTHORIZATION_FLAG,
        action="store_true",
        help="Confirm you intend to spend a real provider call on real input.",
    )
    parser.add_argument("sentence", help="The customer sentence to parse.")
    return parser.parse_args()


def resolve_api_key(settings: AISettings) -> str:
    if settings.gemini_api_key is not None:
        return settings.gemini_api_key.get_secret_value()
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    return getpass.getpass("GEMINI_API_KEY (not echoed): ")


async def run(sentence: str, *, settings: AISettings, api_key: str) -> int:
    async with httpx.AsyncClient() as client:
        provider = GeminiProvider(client=client, settings=settings, api_key=api_key)
        try:
            parsed = await parse_requirements(sentence, provider=provider)
        except InvalidQueryError as error:
            print(f"refused before calling the provider: {error}")
            return 2
        except AIProviderError as error:
            # Deliberately the class name only. Provider errors are built to
            # carry no prompt and no response body, and printing more would
            # undo that.
            print(f"provider failed: {type(error).__name__}")
            return 1

    print(
        json.dumps(
            {
                "model": settings.gemini_model,
                "specification": parsed.specification.model_dump(mode="json"),
                "unresolved": [
                    term.model_dump(mode="json") for term in parsed.unresolved
                ],
                "clarification": parsed.clarification,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    arguments = parse_arguments()
    if not arguments.i_have_authorization:
        print(
            f"refusing: this makes a real provider call. Re-run with "
            f"{AUTHORIZATION_FLAG} if you intend that.",
            file=sys.stderr,
        )
        return 2

    try:
        sentence = validate_query(arguments.sentence)
    except InvalidQueryError as error:
        print(f"refusing: {error}", file=sys.stderr)
        return 2

    settings = load_ai_settings()
    api_key = resolve_api_key(settings)
    if not api_key.strip():
        print("refusing: no API key given.", file=sys.stderr)
        return 2

    try:
        return asyncio.run(run(sentence, settings=settings, api_key=api_key))
    except KeyboardInterrupt:
        return 130
    finally:
        del api_key


def _exit() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _exit()
