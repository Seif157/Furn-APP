"""Prove search works with a real signed-in session. Run it yourself, once.

Every other check in this repository used the anonymous key as the bearer
token, because nothing else had an account. This one signs a real user in to
Supabase and sends that user's token through the complete application: the
real startup, the real Supabase Auth check, the catalogue read under that
user's row-level security, and the real Gemini provider. The only thing
missing compared with the running server is the network socket.

    uv run python -m scripts.live_search_smoke            # search + room plan
    uv run python -m scripts.live_search_smoke --render   # also the preview image

It asks for an email and a password in your terminal. The password is read
without echo, and neither it nor the session token is ever printed, logged, or
written anywhere. Typing them in is the authorization; nothing runs without it.
It spends four Gemini calls, five with --render, and writes nothing
except the preview image when asked for one.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import logging
import sys
import warnings
from pathlib import Path
from typing import NoReturn

import httpx

from app.config import load_settings
from app.main import app
from scripts.live_catalog_smoke import SmokeFailure, sign_in

ROOM_SENTENCE = "عايز أوضة معيشة مودرن فيها كنبة و2 كرسي وترابيزة في حدود 40 ألف"
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


async def run(*, render: bool, skip_rooms: bool) -> int:
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

            if ok and not skip_rooms:
                ok = await check_room(client, headers, render=render) and ok

    del headers
    del session
    print(
        "\nPASSED: search and room planning work with a real signed-in session."
        if ok
        else "\nFAILED"
    )
    return 0 if ok else 1


async def check_room(
    client: httpx.AsyncClient, headers: dict[str, str], *, render: bool
) -> bool:
    print(f"\n{ROOM_SENTENCE}")
    response = await client.post(
        "/v1/rooms/plan", json={"query": ROOM_SENTENCE}, headers=headers
    )
    if response.status_code != 200:
        print(f"  FAILED  room plan HTTP {response.status_code}")
        return False
    plan = response.json()
    print(f"  ok  {plan['summary']}")
    for item in plan["items"]:
        print(
            f"    {item['quantity']} x {item['product']['name']}  "
            f"{item['line_total']}  ({item['colour']})"
        )
    if not render or not plan["image_request"]:
        return True

    print("  rendering the preview, 10 to 20 seconds...")
    image = await client.post(
        "/v1/rooms/image", json=plan["image_request"], headers=headers
    )
    if image.status_code != 200:
        print(f"  FAILED  room preview HTTP {image.status_code}")
        return False
    payload = image.json()
    path = Path(
        "room-preview.png" if "png" in payload["mime_type"] else "room-preview.jpg"
    )
    path.write_bytes(base64.b64decode(payload["image_base64"]))
    print(
        f"  ok  preview saved to {path.resolve()} "
        f"({payload['references_used']} product photos used)"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--render",
        action="store_true",
        help="Also render the room preview image (one image-model call).",
    )
    parser.add_argument("--skip-rooms", action="store_true", help="Check search only.")
    arguments = parser.parse_args()
    try:
        return asyncio.run(
            run(render=arguments.render, skip_rooms=arguments.skip_rooms)
        )
    except KeyboardInterrupt:
        return 130


def _exit() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _exit()
