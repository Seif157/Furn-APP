"""Prove search works with a real signed-in session. Run it yourself, once.

Every other check in this repository used the anonymous key as the bearer
token, because nothing else had an account. This one signs a real user in to
Supabase and sends that user's token through the complete application: the
real startup, the real Supabase Auth check, the catalogue read under that
user's row-level security, and the real Gemini provider. The only thing
missing compared with the running server is the network socket.

    uv run python -m scripts.live_search_smoke

It asks for an email and a password in your terminal. The password is read
without echo, and neither it nor the session token is ever printed, logged, or
written anywhere. Typing them in is the authorization; nothing runs without it.
It spends three Gemini calls and writes nothing.
"""

from __future__ import annotations

import asyncio
import getpass
import logging
import sys
import warnings
from typing import NoReturn

import httpx

from app.config import load_settings
from app.main import app
from scripts.live_catalog_smoke import SmokeFailure, sign_in

SENTENCES = (
    "عايز كنبة مودرن بيج أقل من ٣٠ ألف",
    "a beech wood bed under 20000",
    "عايز كنبة بمية جنيه",
)


def _refuse_terminal() -> NoReturn:
    print(
        "\nrefusing: run this in PowerShell or cmd so the password can be read "
        "without being shown. Git Bash cannot hide it, so it is refused there.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def collect_credentials() -> tuple[str, str]:
    # isatty() alone is not enough: under Git Bash stdin can report a terminal
    # when it is not one, so reading is guarded as well.
    if not sys.stdin.isatty():
        _refuse_terminal()
    try:
        email = input("Email: ").strip()
        with warnings.catch_warnings():
            # Where the password cannot be hidden, getpass warns and then echoes
            # it. Turning the warning into an error refuses instead.
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Password (not shown): ")
    except (EOFError, getpass.GetPassWarning):
        _refuse_terminal()
    if not email or not password:
        print("refusing: email and password are both required.", file=sys.stderr)
        raise SystemExit(2)
    return email, password


def show_search(sentence: str, response: httpx.Response) -> bool:
    print(f"\n{sentence}")
    if response.status_code != 200:
        detail = response.json().get("detail")
        code = detail.get("code") if isinstance(detail, dict) else detail
        print(f"  FAILED  HTTP {response.status_code}  {code}")
        return False

    payload = response.json()
    print(
        f"  ok  language={payload['language']}  "
        f"matched {payload['match_count']} of {payload['candidate_count']}"
    )
    for item in payload["items"][:3]:
        product = item["product"]
        pays = product["discount_price"] or product["price"]
        print(f"    - {product['name']}  pays {pays}")
        for reason in item["reasons"]:
            print(f"        {reason['text']}")
    for alternative in payload["alternatives"]:
        product = alternative["product"]
        pays = product["discount_price"] or product["price"]
        missed = "; ".join(reason["text"] for reason in alternative["missed"])
        print(f"    ~ alternative: {product['name']}  pays {pays}  ({missed})")
    if payload["clarification"]:
        print(f"    asks: {payload['clarification']}")
    return True


async def run() -> int:
    try:
        settings = load_settings()
    except RuntimeError:
        print("refusing: .env configuration is invalid.", file=sys.stderr)
        return 2

    email, password = collect_credentials()
    # httpx logs request URLs at INFO; keep anything token-shaped off screen.
    logging.getLogger("httpx").disabled = True
    logging.getLogger("httpcore").disabled = True

    try:
        async with httpx.AsyncClient() as auth_client:
            session, _ = await sign_in(
                client=auth_client, settings=settings, email=email, password=password
            )
    except SmokeFailure as failure:
        print(f"sign-in failed: {failure.classification}", file=sys.stderr)
        return 1
    finally:
        del password
    print(f"signed in as {email}")

    headers = {"Authorization": f"Bearer {session.access_token.get_secret_value()}"}
    ok = True

    # The application's own startup: settings, Supabase gateways, and the
    # Gemini provider, exactly as the real server builds them.
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://app",
            timeout=90,
        ) as client:
            me = await client.get("/v1/me", headers=headers)
            if me.status_code == 200:
                print("  ok  /v1/me accepted the token")
            else:
                print(f"  FAILED  /v1/me returned HTTP {me.status_code}")
                ok = False

            if ok:
                for sentence in SENTENCES:
                    response = await client.post(
                        "/v1/search",
                        json={"query": sentence, "limit": 3},
                        headers=headers,
                    )
                    ok = show_search(sentence, response) and ok

    del headers
    del session
    print("\nPASSED: search works with a real signed-in session." if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 130


def _exit() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _exit()
