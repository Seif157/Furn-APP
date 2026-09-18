"""Execute the checkout migration against a local PostgreSQL replica.

    uv run --no-project --python 3.12 --with pgserver --with "psycopg[binary]" \\
        python scripts/replica_checkout_test.py

The security SQL tonight hit nine bugs that only a real database could show,
because nothing here executed SQL. This does. It starts a throwaway PostgreSQL
(pgserver, no Docker), rebuilds the tables checkout touches from the columns,
types, defaults, enum labels and constraints recorded from the live database
(docs/evidence), loads Phase 3.2D's real advance_purchase_order and
cancel_purchase_order, applies migrations/checkout-2026-09-18.sql exactly as
the owner will, and drives place_order as a signed-in customer through every
rule it promises. Nothing touches Supabase.

Replica assumptions not in the evidence, each a property the live schema must
already have: product_state has the label 'published'; product_color has
UNIQUE (id, product_id) (order_line_item's composite foreign key needs it)
and CHECK (stock_quantity >= 0).
"""

from __future__ import annotations

import csv
import sys
import tempfile
import uuid
from pathlib import Path

import pgserver
import psycopg

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"
MIGRATION = ROOT / "migrations" / "checkout-2026-09-18.sql"
PHASE_32D = ROOT / "sql" / "phase-3.2d-security-hardening.sql"

TABLES = (
    "category",
    "marketplace_party",
    "customer_profile",
    "address",
    "product",
    "product_color",
    "cart",
    "cart_line",
    "purchase_order",
    "order_line_item",
)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def column_sql(row: dict[str, str]) -> str:
    column_type = row["formatted_type"]
    generated = row.get("generated_kind", "")
    if generated == "s":
        expression = row["default_expression"]
        return f"{row['column_name']} {column_type} GENERATED ALWAYS AS {expression} STORED"
    parts = [row["column_name"], column_type]
    default = row["default_expression"]
    if default and default != "null":
        parts.append(f"DEFAULT {default}")
    if row["is_not_null"] == "true":
        parts.append("NOT NULL")
    return " ".join(parts)


def replica_ddl() -> str:
    statements = [
        "CREATE ROLE anon NOLOGIN",
        "CREATE ROLE authenticated NOLOGIN",
        "CREATE ROLE service_role NOLOGIN BYPASSRLS",
        "CREATE SCHEMA auth",
        "CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$",
        "GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role",
        "GRANT EXECUTE ON FUNCTION auth.uid() TO anon, authenticated, service_role",
    ]

    enums: dict[str, list[tuple[int, str]]] = {}
    for row in rows(EVIDENCE / "phase-3.2d" / "state-enums.csv"):
        enums.setdefault(row["enum_type_name"], []).append(
            (int(row["label_order"]), row["label"])
        )
    enums["product_state"] = [(1, "draft"), (2, "published"), (3, "archived")]
    for name, labels in enums.items():
        values = ", ".join(f"'{label}'" for _, label in sorted(labels))
        statements.append(f"CREATE TYPE public.{name} AS ENUM ({values})")

    columns: dict[str, list[dict[str, str]]] = {table: [] for table in TABLES}
    for row in rows(EVIDENCE / "phase-3.2d" / "column-inventory.csv"):
        if row["table_name"] in columns:
            columns[row["table_name"]].append(row)
    seen_catalogue: set[tuple[str, str]] = set()
    for row in rows(EVIDENCE / "phase-4a" / "section-01.csv"):
        key = (row["table_name"], row["column_name"])
        if row["table_name"] in ("category", "product", "product_color") and (
            key not in seen_catalogue
        ):
            seen_catalogue.add(key)
            columns[row["table_name"]].append(row)

    for table in TABLES:
        assert columns[table], f"no recorded columns for {table}"
        ordered = sorted(columns[table], key=lambda r: int(r["ordinal_position"]))
        body = ",\n    ".join(column_sql(r) for r in ordered)
        statements.append(f"CREATE TABLE public.{table} (\n    {body}\n)")

    # Every table's primary key is its id; added first so foreign keys can
    # reference them.
    for table in TABLES:
        statements.append(f"ALTER TABLE public.{table} ADD PRIMARY KEY (id)")
    statements.append(
        "ALTER TABLE public.product_color ADD CONSTRAINT product_color_id_product_unique "
        "UNIQUE (id, product_id)"
    )
    # Constraints recorded live; foreign keys only between replicated tables.
    for row in rows(EVIDENCE / "phase-3.2d" / "constraints.csv"):
        table = row["table_name"]
        if table not in TABLES or row["constraint_kind"] == "p":
            continue
        referenced = row.get("referenced_table") or ""
        if row["constraint_kind"] == "f" and referenced not in TABLES:
            continue
        statements.append(
            f"ALTER TABLE public.{table} ADD CONSTRAINT {row['constraint_name']} "
            f"{row['definition']}"
        )
    statements += [
        "ALTER TABLE public.product_color ADD CONSTRAINT product_color_stock_non_negative "
        "CHECK (stock_quantity >= 0)",
        "ALTER TABLE public.product ADD FOREIGN KEY (marketplace_party_id) "
        "REFERENCES public.marketplace_party (id)",
        "ALTER TABLE public.product ADD FOREIGN KEY (category_id) "
        "REFERENCES public.category (id)",
        "ALTER TABLE public.product_color ADD FOREIGN KEY (product_id) "
        "REFERENCES public.product (id)",
    ]
    for table in TABLES:
        statements.append(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    return statements


def phase_32d_order_functions() -> str:
    """The real 3.2D order functions, extracted verbatim."""

    text = PHASE_32D.read_text(encoding="utf-8").replace("\r\n", "\n")
    blocks = []
    for name in ("advance_purchase_order", "cancel_purchase_order"):
        start = text.index(f"CREATE OR REPLACE FUNCTION public.{name}(")
        end = text.index("TO authenticated, service_role;", start) + len(
            "TO authenticated, service_role;"
        )
        blocks.append(text[start:end])
    return "\n\n".join(blocks)


class Replica:
    def __init__(self, url: str) -> None:
        self.url = url

    def admin(self) -> psycopg.Connection:
        return psycopg.connect(self.url, autocommit=True)

    def as_user(self, user_id: uuid.UUID | None, role: str = "authenticated"):
        conn = psycopg.connect(self.url, autocommit=True)
        conn.execute(f"SET ROLE {role}")
        if user_id is not None:
            conn.execute(
                "SELECT set_config('request.jwt.claim.sub', %s, false)", (str(user_id),)
            )
        return conn


FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("  ok    " if condition else "  FAIL  ") + label)
    if not condition:
        FAILURES.append(label)


def expect_error(conn, sql: str, params, message: str, label: str) -> None:
    try:
        conn.execute(sql, params)
    except psycopg.errors.RaiseException as error:
        check(error.diag.message_primary == message, f"{label} -> {message}")
        return
    except psycopg.Error as error:  # any other error is also a failure
        check(False, f"{label} -> expected {message}, got {error!r}")
        return
    check(False, f"{label} -> expected {message}, got success")


def main() -> int:
    data_dir = tempfile.mkdtemp(prefix="furn-replica-")
    server = pgserver.get_server(data_dir, cleanup_mode="delete")
    url = server.get_uri()
    replica = Replica(url)

    with replica.admin() as db:
        for statement in replica_ddl():
            db.execute(statement)
        db.execute(phase_32d_order_functions())
    print("replica built from evidence; 3.2D order functions loaded")

    # Apply the migration exactly as the owner will: the whole file at once.
    with replica.admin() as db:
        db.execute(MIGRATION.read_text(encoding="utf-8"))
    print("migration applied\n")

    with replica.admin() as db:
        try:
            db.execute(MIGRATION.read_text(encoding="utf-8"))
            check(False, "a second run refuses")
        except psycopg.errors.RaiseException as error:
            check(
                "already applied" in error.diag.message_primary, "a second run refuses"
            )

    # --- data ------------------------------------------------------------------
    ids = {
        name: uuid.uuid4()
        for name in (
            "buyer_user",
            "buyer",
            "other_user",
            "other",
            "seller_a_user",
            "seller_b_user",
            "seller_a",
            "seller_b",
            "category",
            "hidden_category",
            "sofa",
            "chair",
            "draft_bed",
            "sofa_grey",
            "chair_beige",
            "bed_white",
            "address",
            "other_address",
            "cart",
            "stranger_user",
        )
    }
    with replica.admin() as db:
        db.execute(
            "INSERT INTO category (id, name, is_active) VALUES (%s, 'Sofas', true), (%s, 'Hidden', false)",
            (ids["category"], ids["hidden_category"]),
        )
        db.execute(
            "INSERT INTO marketplace_party (id, user_id, business_name, approval_state) VALUES "
            "(%s, %s, 'Seller A', 'approved'), (%s, %s, 'Seller B', 'approved')",
            (
                ids["seller_a"],
                ids["seller_a_user"],
                ids["seller_b"],
                ids["seller_b_user"],
            ),
        )
        db.execute(
            "INSERT INTO customer_profile (id, user_id, full_name) VALUES (%s, %s, 'Buyer'), (%s, %s, 'Other')",
            (ids["buyer"], ids["buyer_user"], ids["other"], ids["other_user"]),
        )
        db.execute(
            "INSERT INTO address (id, customer_profile_id, recipient_name, contact_phone, address_line_1, city, country, latitude, longitude) VALUES "
            "(%s, %s, 'Buyer', '010', '1 Nile St', 'Cairo', 'EG', 30.0444, 31.2357), "
            "(%s, %s, 'Other', '011', '2 Sea St', 'Alexandria', 'EG', NULL, NULL)",
            (ids["address"], ids["buyer"], ids["other_address"], ids["other"]),
        )
        db.execute(
            "INSERT INTO product (id, marketplace_party_id, category_id, name, price, discount_price, lifecycle_state) VALUES "
            "(%s, %s, %s, 'Modern Sofa', 15000, 13500, 'published'), "
            "(%s, %s, %s, 'Dining Chair', 2000, NULL, 'published'), "
            "(%s, %s, %s, 'Draft Bed', 9000, NULL, 'draft')",
            (
                ids["sofa"],
                ids["seller_a"],
                ids["category"],
                ids["chair"],
                ids["seller_b"],
                ids["category"],
                ids["draft_bed"],
                ids["seller_a"],
                ids["category"],
            ),
        )
        db.execute(
            "INSERT INTO product_color (id, product_id, color_value, stock_quantity) VALUES "
            "(%s, %s, 'grey', 3), (%s, %s, 'beige', 5), (%s, %s, 'white', 4)",
            (
                ids["sofa_grey"],
                ids["sofa"],
                ids["chair_beige"],
                ids["chair"],
                ids["bed_white"],
                ids["draft_bed"],
            ),
        )
        db.execute(
            "INSERT INTO cart (id, customer_profile_id) VALUES (%s, %s)",
            (ids["cart"], ids["buyer"]),
        )

    def stock(color: str) -> int:
        with replica.admin() as db:
            return db.execute(
                "SELECT stock_quantity FROM product_color WHERE id = %s", (ids[color],)
            ).fetchone()[0]

    def set_cart(lines: list[tuple[str, int]]) -> None:
        with replica.admin() as db:
            db.execute("DELETE FROM cart_line WHERE cart_id = %s", (ids["cart"],))
            for color, quantity in lines:
                db.execute(
                    "INSERT INTO cart_line (cart_id, product_color_id, quantity) VALUES (%s, %s, %s)",
                    (ids["cart"], ids[color], quantity),
                )

    def count(sql: str, params=()) -> int:
        with replica.admin() as db:
            return db.execute(sql, params).fetchone()[0]

    place = "SELECT public.place_order(%s)"

    # --- refusals, and that nothing changes ------------------------------------
    print("refusals")
    with replica.as_user(None, "anon") as anon:
        try:
            anon.execute(place, (ids["address"],))
            check(False, "anonymous callers cannot execute place_order")
        except psycopg.errors.InsufficientPrivilege:
            check(True, "anonymous callers cannot execute place_order")
    with replica.as_user(ids["stranger_user"]) as stranger:
        expect_error(
            stranger,
            place,
            (ids["address"],),
            "customer_profile_required",
            "account without a customer profile",
        )
    with replica.as_user(ids["buyer_user"]) as buyer:
        expect_error(
            buyer,
            place,
            (ids["other_address"],),
            "address_not_found",
            "someone else's address",
        )
        set_cart([])
        expect_error(buyer, place, (ids["address"],), "cart_empty", "empty cart")
        set_cart([("sofa_grey", 1), ("bed_white", 1)])
        expect_error(
            buyer,
            place,
            (ids["address"],),
            "product_unavailable",
            "an unpublished product in the cart",
        )
        set_cart([("sofa_grey", 4)])
        expect_error(
            buyer, place, (ids["address"],), "insufficient_stock", "more than the stock"
        )
    check(
        count("SELECT count(*) FROM purchase_order") == 0,
        "no order was written by any refusal",
    )
    check(stock("sofa_grey") == 3, "no stock moved on any refusal")

    with replica.admin() as db:
        db.execute(
            "UPDATE product SET category_id = %s WHERE id = %s",
            (ids["hidden_category"], ids["chair"]),
        )
    set_cart([("chair_beige", 1)])
    with replica.as_user(ids["buyer_user"]) as buyer:
        expect_error(
            buyer,
            place,
            (ids["address"],),
            "product_unavailable",
            "a product in an inactive category",
        )
    with replica.admin() as db:
        db.execute(
            "UPDATE product SET category_id = %s WHERE id = %s",
            (ids["category"], ids["chair"]),
        )
        db.execute(
            "UPDATE marketplace_party SET approval_state = 'suspended', state_reason = 'test' WHERE id = %s",
            (ids["seller_b"],),
        )
    with replica.as_user(ids["buyer_user"]) as buyer:
        expect_error(
            buyer, place, (ids["address"],), "product_unavailable", "a suspended seller"
        )
    with replica.admin() as db:
        db.execute(
            "UPDATE marketplace_party SET approval_state = 'approved', state_reason = NULL WHERE id = %s",
            (ids["seller_b"],),
        )

    # --- a two-seller checkout -------------------------------------------------
    print("\ncheckout: 2 grey sofas (seller A, discounted) + 3 beige chairs (seller B)")
    set_cart([("sofa_grey", 2), ("chair_beige", 3)])
    with replica.as_user(ids["buyer_user"]) as buyer:
        placed = buyer.execute(place, (ids["address"],)).fetchone()[0]
    check(len(placed) == 2, "one order per seller (2)")
    with replica.admin() as db:
        orders = db.execute(
            "SELECT id, marketplace_party_id, customer_profile_id, address_id, origin::text, "
            "lifecycle_state::text, delivery_fee, required_upfront_amount, ship_recipient_name, "
            "ship_city, ship_latitude, ship_longitude FROM purchase_order ORDER BY marketplace_party_id"
        ).fetchall()
        lines = db.execute(
            "SELECT o.marketplace_party_id, l.line_kind::text, l.item_name, l.specification, "
            "l.unit_price, l.quantity, l.line_total FROM order_line_item l "
            "JOIN purchase_order o ON o.id = l.order_id"
        ).fetchall()
    by_seller = {row[1]: row for row in orders}
    check(
        set(by_seller) == {ids["seller_a"], ids["seller_b"]},
        "orders go to the two sellers",
    )
    check(
        all(r[2] == ids["buyer"] and r[3] == ids["address"] for r in orders),
        "orders belong to the buyer and address",
    )
    check(
        all(r[4] == "stocked" and r[5] == "pending" for r in orders),
        "origin stocked, state pending",
    )
    check(
        all(r[6] == 0 and r[7] is None for r in orders),
        "delivery free, nothing upfront (cash on delivery)",
    )
    check(
        all(
            r[8] == "Buyer"
            and r[9] == "Cairo"
            and r[10] is not None
            and r[11] is not None
            for r in orders
        ),
        "shipping address snapshot copied",
    )
    line_by_seller = {row[0]: row for row in lines}
    sofa = line_by_seller[ids["seller_a"]]
    chair = line_by_seller[ids["seller_b"]]
    check(
        sofa[1:] == ("catalog", "Modern Sofa", "grey", 13500, 2, 27000),
        f"sofa line uses the discount price: {sofa[1:]}",
    )
    check(
        chair[1:] == ("catalog", "Dining Chair", "beige", 2000, 3, 6000),
        f"chair line uses the list price: {chair[1:]}",
    )
    check(
        stock("sofa_grey") == 1 and stock("chair_beige") == 2,
        "stock reserved (3->1, 5->2)",
    )
    check(
        count("SELECT count(*) FROM cart_line WHERE cart_id = %s", (ids["cart"],)) == 0,
        "cart emptied",
    )
    check(
        count("SELECT count(*) FROM checkout_private.stock_reservation") == 2,
        "two reservations recorded",
    )

    # --- cancel returns stock once; delivered keeps it --------------------------
    print("\ncancel and deliver, through 3.2D's real functions")
    sofa_order = by_seller[ids["seller_a"]][0]
    chair_order = by_seller[ids["seller_b"]][0]
    with replica.as_user(ids["buyer_user"]) as buyer:
        cancelled = buyer.execute(
            "SELECT public.cancel_purchase_order(%s)", (sofa_order,)
        ).fetchone()[0]
    check(cancelled is True, "customer cancels the pending sofa order")
    check(stock("sofa_grey") == 3, "cancel returned the 2 sofas (1->3)")
    with replica.admin() as db:
        db.execute(
            "UPDATE purchase_order SET lifecycle_state = 'pending', cancelled_at = NULL WHERE id = %s",
            (sofa_order,),
        )
        db.execute(
            "UPDATE purchase_order SET lifecycle_state = 'cancelled', cancelled_at = now() WHERE id = %s",
            (sofa_order,),
        )
    check(stock("sofa_grey") == 3, "a second cancellation returns nothing more")
    with replica.as_user(ids["seller_b_user"]) as seller:
        for state in ("confirmed", "preparing", "out_for_delivery", "delivered"):
            seller.execute(
                "SELECT public.advance_purchase_order(%s, %s)", (chair_order, state)
            )
    with replica.admin() as db:
        final_state = db.execute(
            "SELECT lifecycle_state::text FROM purchase_order WHERE id = %s",
            (chair_order,),
        ).fetchone()[0]
    check(final_state == "delivered", "seller advances the chair order to delivered")
    check(stock("chair_beige") == 2, "delivery keeps the stock consumed")
    check(
        count("SELECT count(*) FROM checkout_private.stock_reservation") == 0,
        "no reservations left",
    )

    # --- the private schema is private ------------------------------------------
    print("\nprivacy")
    with replica.as_user(ids["buyer_user"]) as buyer:
        try:
            buyer.execute("SELECT count(*) FROM checkout_private.stock_reservation")
            check(False, "customers cannot read reservations")
        except psycopg.errors.InsufficientPrivilege:
            check(True, "customers cannot read reservations")

    # --- the last unit, two buyers at once ---------------------------------------
    print("\nthe last unit, two checkouts at the same moment")
    with replica.admin() as db:
        db.execute(
            "UPDATE product_color SET stock_quantity = 1 WHERE id = %s",
            (ids["sofa_grey"],),
        )
        other_cart = db.execute(
            "INSERT INTO cart (customer_profile_id) VALUES (%s) RETURNING id",
            (ids["other"],),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO cart_line (cart_id, product_color_id, quantity) VALUES (%s, %s, 1)",
            (other_cart, ids["sofa_grey"]),
        )
        db.execute(
            "UPDATE address SET customer_profile_id = customer_profile_id WHERE id = %s",
            (ids["other_address"],),
        )
    set_cart([("sofa_grey", 1)])
    first = psycopg.connect(url)
    first.execute("SET ROLE authenticated")
    first.execute(
        "SELECT set_config('request.jwt.claim.sub', %s, false)",
        (str(ids["buyer_user"]),),
    )
    first.execute(place, (ids["address"],))  # holds the lock, not yet committed
    import threading

    outcome: dict[str, str] = {}

    def second_buyer() -> None:
        with replica.as_user(ids["other_user"]) as other:
            try:
                other.execute(place, (ids["other_address"],))
                outcome["second"] = "placed"
            except psycopg.errors.RaiseException as error:
                outcome["second"] = error.diag.message_primary

    thread = threading.Thread(target=second_buyer)
    thread.start()
    thread.join(timeout=2)
    check(thread.is_alive(), "the second checkout waits for the first")
    first.commit()
    first.close()
    thread.join(timeout=10)
    check(
        outcome.get("second") == "insufficient_stock",
        f"the second buyer is refused: {outcome.get('second')}",
    )
    check(stock("sofa_grey") == 0, "stock never goes below zero")

    # --- verification query, undo, and a clean re-apply --------------------------
    print("\nverification, undo, re-apply")
    verify = (ROOT / "migrations" / "checkout-2026-09-18-verify.sql").read_text(
        encoding="utf-8"
    )
    undo = (ROOT / "migrations" / "checkout-2026-09-18-undo.sql").read_text(
        encoding="utf-8"
    )
    with replica.admin() as db:
        results = db.execute(verify).fetchall()
        check(
            len(results) == 8 and all(passed for _, passed in results),
            f"verification: {sum(p for _, p in results)}/{len(results)} checks pass",
        )
        db.execute(undo)
        gone = db.execute(
            "SELECT to_regprocedure('public.place_order(uuid)') IS NULL "
            "AND to_regnamespace('checkout_private') IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'settle_stock_reservation')"
        ).fetchone()[0]
        check(gone, "undo removes the function, trigger and private schema")
        orders_kept = db.execute("SELECT count(*) FROM purchase_order").fetchone()[0]
        check(orders_kept == 3, "undo keeps the orders already placed")
        db.execute(MIGRATION.read_text(encoding="utf-8"))
        results = db.execute(verify).fetchall()
        check(
            all(passed for _, passed in results),
            "the migration applies again after undo",
        )

    server.cleanup()
    print(f"\n{'PASSED' if not FAILURES else 'FAILED'}: {len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
