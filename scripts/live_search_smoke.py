"""Prove search works with a real signed-in session. Run it yourself, once.

Every other check in this repository used the anonymous key as the bearer
token, because nothing else had an account. This one signs a real user in to
Supabase and sends that user's token through the complete application: the
real startup, the real Supabase Auth check, the catalogue read under that
user's row-level security, and the real Gemini provider. The only thing
missing compared with the running server is the network socket.

    uv run python -m scripts.live_search_smoke            # search + room plan
    uv run python -m scripts.live_search_smoke --render   # also the preview image
    uv run python -m scripts.live_search_smoke --cart     # also create/fetch the cart
    uv run python -m scripts.live_search_smoke --checkout # also order one item, cancel

It asks for an email and a password in your terminal. The password is read
without echo, and neither it nor the session token is ever printed, logged, or
written anywhere. Typing them in is the authorization; nothing runs without it.
It spends nine Gemini calls, ten with --render, or six with
--skip-intake. It writes nothing except the
preview image file when asked for one, and, only with --cart, this account's
one empty cart in Supabase if it has none yet.
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
    # Nothing in the catalogue states a feel, so this one is answered entirely
    # by the inferred tags applied on 2026-09-20. Its reasons should carry
    # "(our guess)" / "(تقديرنا)"; without tags it ranks on the words alone.
    "عايز كنبة دافئة ومريحة للريسبشن",
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
    if payload.get("personalized"):
        print("      (ordering used this customer's own purchase history)")
    for item in payload["items"][:3]:
        product = item["product"]
        pays = product["discount_price"] or product["price"]
        print(f"    - {product['name']}  pays {pays}")
        for reason in item["reasons"]:
            # A guess is marked here exactly as the app must mark it.
            mark = "~" if reason.get("basis") == "inferred" else " "
            print(f"      {mark} {reason['text']}")
    for alternative in payload["alternatives"]:
        product = alternative["product"]
        pays = product["discount_price"] or product["price"]
        missed = "; ".join(reason["text"] for reason in alternative["missed"])
        print(f"    ~ alternative: {product['name']}  pays {pays}  ({missed})")
    for offer in payload.get("seller_offers", []):
        print(f"    + made to order: {offer['title']}  ({offer['label']})")
    if payload["clarification"]:
        print(f"    asks: {payload['clarification']}")
    asked = payload.get("follow_up")
    if asked:
        options = " / ".join(option["label"] for option in asked["options"])
        print(f"    offers: {asked['question']}  [{options}]")
    return True


async def run(
    *,
    render: bool,
    skip_rooms: bool,
    skip_intake: bool,
    cart: bool,
    checkout: bool,
) -> int:
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

            if ok:
                ok = await check_meta_and_refinement(client, headers) and ok

            if ok:
                ok = await check_compare_and_similar(client, headers) and ok

            if ok and not skip_intake:
                ok = await check_intake(client, headers) and ok

            if ok and cart:
                ok = await check_cart(client, headers) and ok

            if ok and checkout:
                ok = await check_checkout(client, headers, settings) and ok

            if ok and not skip_rooms:
                ok = await check_room(client, headers, render=render) and ok

    del headers
    del session
    checked = "search, follow-ups, compare, similar, public reviews"
    if not skip_intake:
        checked += ", service triage, the furnishing brief"
    if cart:
        checked += ", the cart"
    if checkout:
        checked += ", checkout and cancellation"
    if not skip_rooms:
        checked += " and room planning"
    print(
        f"\nPASSED: {checked} work with a real signed-in session." if ok else "\nFAILED"
    )
    return 0 if ok else 1


async def check_checkout(
    client: httpx.AsyncClient, headers: dict[str, str], settings
) -> bool:
    """Place a one-item order as the app will (Supabase RPC with the customer's
    own token), then cancel it and require the stock to come back."""

    print("\ncheckout: one item, place_order, then cancel_purchase_order")
    rest = f"{str(settings.supabase_url).rstrip('/')}/rest/v1"
    supabase = {
        **headers,
        "apikey": settings.supabase_publishable_key.get_secret_value(),
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as db:
        cart_id = (await client.post("/v1/cart", headers=headers)).json()["cart_id"]
        lines = await db.get(
            f"{rest}/cart_line",
            params={"select": "id", "cart_id": f"eq.{cart_id}"},
            headers=supabase,
        )
        if lines.status_code != 200 or lines.json():
            print(
                "  FAILED  the cart is not empty; empty it first so nothing "
                "unintended is ordered"
            )
            return False
        addresses = await db.get(
            f"{rest}/address", params={"select": "id", "limit": "1"}, headers=supabase
        )
        if addresses.status_code != 200 or not addresses.json():
            print("  FAILED  this account has no address; add one in the app first")
            return False
        address_id = addresses.json()[0]["id"]

        listing = await client.get("/v1/catalog/products?limit=50", headers=headers)
        choice = next(
            (
                (product["name"], colour["id"])
                for product in listing.json()["items"]
                for colour in product["colors"]
                if colour["stock_quantity"] >= 2
            ),
            None,
        )
        if choice is None:
            print("  FAILED  no product colour with stock to test with")
            return False
        name, colour_id = choice

        async def stock() -> int:
            response = await db.get(
                f"{rest}/product_color",
                params={"select": "stock_quantity", "id": f"eq.{colour_id}"},
                headers=supabase,
            )
            return response.json()[0]["stock_quantity"]

        before = await stock()
        added = await db.post(
            f"{rest}/cart_line",
            json={"cart_id": cart_id, "product_color_id": colour_id, "quantity": 1},
            headers={**supabase, "Prefer": "return=minimal"},
        )
        if added.status_code not in (200, 201):
            print(f"  FAILED  adding to cart: HTTP {added.status_code} {added.text}")
            return False
        placed = await db.post(
            f"{rest}/rpc/place_order", json={"address_id": address_id}, headers=supabase
        )
        if placed.status_code != 200:
            print(f"  FAILED  place_order: HTTP {placed.status_code} {placed.text}")
            return False
        orders = placed.json()
        after_order = await stock()
        print(
            f"  ok  placed {len(orders)} order(s) for 1 x {name}; "
            f"stock {before} -> {after_order}"
        )
        cancelled = [
            (
                await db.post(
                    f"{rest}/rpc/cancel_purchase_order",
                    json={"order_id": order["order_id"]},
                    headers=supabase,
                )
            ).json()
            for order in orders
        ]
        after_cancel = await stock()
        print(f"  ok  cancelled: {cancelled}; stock {after_order} -> {after_cancel}")
    good = (
        len(orders) == 1
        and after_order == before - 1
        and cancelled == [True]
        and after_cancel == before
    )
    if not good:
        print("  FAILED  expected one order, stock down by 1, then back after cancel")
    return good


async def check_cart(client: httpx.AsyncClient, headers: dict[str, str]) -> bool:
    """The first call may create the cart; the second must return the same one."""

    print("\ncart (POST /v1/cart twice)")
    first = await client.post("/v1/cart", headers=headers)
    second = await client.post("/v1/cart", headers=headers)
    if first.status_code != 200 or second.status_code != 200:
        codes = [
            (r.status_code, r.json().get("detail", {}).get("code"))
            for r in (first, second)
        ]
        print(f"  FAILED  {codes}")
        return False
    a, b = first.json(), second.json()
    same = a["cart_id"] == b["cart_id"] and not b["created"]
    print(
        f"  {'ok' if same else 'FAILED'}  first call created={a['created']}, "
        f"second call created={b['created']}, same cart={a['cart_id'] == b['cart_id']}"
    )
    return same


async def check_meta_and_refinement(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> bool:
    """What the app asks on startup, and a follow-up that refines a search."""

    meta = await client.get("/v1/meta")
    if meta.status_code != 200 or not meta.json()["features"]["search"]:
        print(f"\n  FAILED  /v1/meta HTTP {meta.status_code} or search off")
        return False
    print("\n  ok  /v1/meta reports search on")

    first, follow_up = "عايز كنبة مودرن أقل من ٣٠ ألف", "خليها رمادي"
    print(f"\n{first} ... {follow_up}")
    response = await client.post(
        "/v1/search",
        json={"query": follow_up, "history": [first], "limit": 3},
        headers=headers,
    )
    if response.status_code != 200:
        print(f"  FAILED  refinement HTTP {response.status_code}")
        return False
    understood = response.json()["interpretation"]
    price = understood["price"]["maximum"] if understood["price"] else None
    category = understood["category"]["slug"] if understood["category"] else None
    colours = [
        t["slug"] for t in understood["preferred_colours"] + understood["colours"]
    ]
    print(f"  ok  category={category} max_price={price} colours={colours}")
    if category != "sofas" or price is None or "grey" not in colours:
        print("  FAILED  the follow-up did not keep the sofa and budget and add grey")
        return False

    reviews = await client.get("/v1/catalog/products?limit=1", headers=headers)
    product_id = reviews.json()["items"][0]["id"]
    public = await client.get(f"/v1/reviews/public?product_id={product_id}")
    if public.status_code != 200:
        print(f"  FAILED  public reviews HTTP {public.status_code}")
        return False
    print(
        f"  ok  public reviews readable ({len(public.json()['items'])} for one product)"
    )
    return True


async def check_intake(client: httpx.AsyncClient, headers: dict[str, str]) -> bool:
    """The two intake endpoints, against the marketplace's real service list.

    Three model calls. The washing machine is deliberate: every service in the
    live directory is a bare name with no description, and "Repair" on its own
    once matched an appliance at 0.95. Asking for it here is how that stays
    fixed.
    """

    problem = "باب الدولاب اتكسر"
    print(f"\n{problem}")
    response = await client.post(
        "/v1/intake/service", json={"description": problem}, headers=headers
    )
    if response.status_code != 200:
        detail = response.json().get("detail")
        code = detail.get("code") if isinstance(detail, dict) else detail
        print(f"  FAILED  intake HTTP {response.status_code}  {code}")
        return False
    payload = response.json()
    for service in payload["services"]:
        print(f"    - {service['name']}  {service['confidence']}")
    if payload["clarification"]:
        print(f"    asks: {payload['clarification']}")
    if not payload["services"]:
        print("  FAILED  a broken wardrobe door matched no service")
        return False
    print("  ok  routed to a real service from the live directory")

    off_topic = "عايز حد يصلح الغسالة"
    print(f"\n{off_topic}")
    response = await client.post(
        "/v1/intake/service", json={"description": off_topic}, headers=headers
    )
    if response.status_code != 200:
        print(f"  FAILED  intake HTTP {response.status_code}")
        return False
    matched = response.json()["services"]
    if matched:
        names = ", ".join(s["name"] for s in matched)
        print(f"  FAILED  a washing machine was routed to {names}")
        return False
    print("  ok  not furniture, so no service was offered")

    job = "عايز أفرش شقة فيها ٣ أوض نوم وريسبشن بميزانية ١٥٠ ألف، ستايل مودرن"
    print(f"\n{job}")
    response = await client.post(
        "/v1/intake/furnishing", json={"description": job}, headers=headers
    )
    if response.status_code != 200:
        print(f"  FAILED  furnishing brief HTTP {response.status_code}")
        return False
    brief = response.json()
    rooms = {r["room_type"]["slug"]: r["quantity"] for r in brief["rooms"]}
    styles = [t["slug"] for t in brief["styles"]]
    print(f"    rooms={rooms} budget={brief['total_budget']} styles={styles}")
    for term in brief["unresolved"]:
        print(f"    unresolved: {term['surface']}")
    if rooms != {"bedroom": 3, "reception": 1} or brief["total_budget"] != "150000":
        print("  FAILED  the flat did not become the form it should")
        return False
    print("  ok  the job became a form the app can prefill")
    return True


async def check_compare_and_similar(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> bool:
    """No model call: similar products for one real product, then a comparison
    of it with the first two suggestions."""

    listing = await client.get("/v1/catalog/products?limit=1", headers=headers)
    if listing.status_code != 200 or not listing.json()["items"]:
        print(f"\n  FAILED  catalogue listing HTTP {listing.status_code}")
        return False
    product = listing.json()["items"][0]
    print(f"\nsimilar to {product['name']}")
    similar = await client.get(
        f"/v1/catalog/products/{product['id']}/similar?limit=3&language=ar",
        headers=headers,
    )
    if similar.status_code != 200:
        print(f"  FAILED  similar HTTP {similar.status_code}")
        return False
    items = similar.json()["items"]
    print(f"  ok  {len(items)} suggestions")
    for item in items:
        reasons = "; ".join(reason["text"] for reason in item["reasons"])
        print(f"    - {item['product']['name']}  ({reasons})")
    if not items:
        return True

    ids = [product["id"], *(item["product"]["id"] for item in items[:2])]
    comparison = await client.post(
        "/v1/compare", json={"product_ids": ids, "language": "ar"}, headers=headers
    )
    if comparison.status_code != 200:
        print(f"  FAILED  compare HTTP {comparison.status_code}")
        return False
    print(f"  ok  compared {len(ids)} products")
    for sentence in comparison.json()["summary"]:
        print(f"    {sentence['text']}")
    return True


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
    parser.add_argument(
        "--skip-intake",
        action="store_true",
        help="Skip service triage and the furnishing brief (saves three calls).",
    )
    parser.add_argument(
        "--cart",
        action="store_true",
        help="Also call POST /v1/cart twice. Creates this account's one empty "
        "cart if it has none: a real write.",
    )
    parser.add_argument(
        "--checkout",
        action="store_true",
        help="Also place a real one-item order with place_order, then cancel it "
        "and check the stock came back. Real writes: a cancelled order stays on "
        "record. Refuses if the cart is not empty.",
    )
    arguments = parser.parse_args()
    try:
        return asyncio.run(
            run(
                render=arguments.render,
                skip_rooms=arguments.skip_rooms,
                skip_intake=arguments.skip_intake,
                cart=arguments.cart or arguments.checkout,
                checkout=arguments.checkout,
            )
        )
    except KeyboardInterrupt:
        return 130


def _exit() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _exit()
