"""Execute the product_search_tag migration against a local PostgreSQL replica.

    uv run --no-project --python 3.12 --with pgserver --with "psycopg[binary]" \\
        python scripts/replica_search_tags_test.py

The migration only touches two things that already exist live: public.product's
id and lifecycle_state, and the Phase 3.2D policy it checks for. Those are
stubbed here, clearly and minimally; everything the migration itself creates is
the real file, applied as the owner will apply it, and then exercised as anon
and as a signed-in customer with row-level security enforced.

What this proves that a static test cannot: the table's constraints reject the
rows the API could not use, clients can read published tags and write none, and
the undo really removes it. Nothing touches Supabase.
"""

from __future__ import annotations

import sys
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pgserver
import psycopg

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "product-search-tags-2026-09-20.sql"
UNDO = ROOT / "migrations" / "product-search-tags-2026-09-20-undo.sql"
VERIFY = ROOT / "migrations" / "product-search-tags-2026-09-20-verify.sql"

# From app/catalog/upstream_models.py, which is validated against live rows on
# every catalogue read, and from Phase 3.2B, which writes 'published' into its
# policies.
PRODUCT_STATES = ("draft", "published", "hidden", "archived")

FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("  ok    " if condition else "  FAIL  ") + label)
    if not condition:
        FAILURES.append(label)


def build(db: psycopg.Connection) -> dict[str, uuid.UUID]:
    """Stub the two live things the migration depends on, and nothing more."""

    for role in ("anon", "authenticated", "service_role"):
        db.execute(f"CREATE ROLE {role} NOLOGIN")
    values = ", ".join(f"'{state}'" for state in PRODUCT_STATES)
    db.execute(f"CREATE TYPE public.product_state AS ENUM ({values})")
    db.execute(
        "CREATE TABLE public.product ("
        "id uuid PRIMARY KEY, "
        "name text NOT NULL, "
        "lifecycle_state public.product_state NOT NULL)"
    )
    db.execute("ALTER TABLE public.product ENABLE ROW LEVEL SECURITY")
    db.execute("GRANT SELECT ON public.product TO anon, authenticated")
    db.execute(
        "CREATE POLICY published_products ON public.product FOR SELECT "
        "TO anon, authenticated USING (lifecycle_state = 'published')"
    )
    # The 3.2D marker the migration's preflight looks for. The table it sits on
    # is irrelevant here; only the policy's existence is checked.
    db.execute("CREATE TABLE public.furnishing_request_design_version (id uuid)")
    db.execute(
        "ALTER TABLE public.furnishing_request_design_version ENABLE ROW LEVEL SECURITY"
    )
    db.execute(
        "CREATE POLICY phase32d_furnishing_request_design_version_delete_own "
        "ON public.furnishing_request_design_version FOR DELETE "
        "TO authenticated USING (true)"
    )

    ids = {name: uuid.uuid4() for name in ("published", "draft")}
    for name, product_id in ids.items():
        db.execute(
            "INSERT INTO public.product (id, name, lifecycle_state) "
            "VALUES (%s, %s, %s)",
            (
                product_id,
                f"{name} sofa",
                "published" if name == "published" else "draft",
            ),
        )
    return ids


def tag(db: psycopg.Connection, product_id: uuid.UUID, **overrides: object) -> None:
    row = {
        "tag_kind": "style",
        "tag_slug": "modern",
        "confidence": "0.80",
        "model_name": "gemini-3.6-flash",
    }
    row.update(overrides)
    db.execute(
        "INSERT INTO public.product_search_tag "
        "(product_id, tag_kind, tag_slug, confidence, model_name) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            product_id,
            row["tag_kind"],
            row["tag_slug"],
            row["confidence"],
            row["model_name"],
        ),
    )


def refuses(db: psycopg.Connection, product_id: uuid.UUID, **overrides: object) -> bool:
    try:
        with db.transaction():
            tag(db, product_id, **overrides)
    except (psycopg.errors.CheckViolation, psycopg.errors.NumericValueOutOfRange):
        return True
    except psycopg.errors.UniqueViolation:
        return True
    return False


def main() -> int:
    server = pgserver.get_server(
        tempfile.mkdtemp(prefix="furn-tags-"), cleanup_mode="delete"
    )
    url = server.get_uri()

    with psycopg.connect(url, autocommit=True) as db:
        ids = build(db)
        db.execute(MIGRATION.read_text(encoding="utf-8"))
        print("replica built; migration applied\n")

        print("the migration itself")
        try:
            db.execute(MIGRATION.read_text(encoding="utf-8"))
            check(False, "a second run refuses")
        except psycopg.errors.RaiseException as error:
            check(
                "already applied" in (error.diag.message_primary or ""),
                "a second run refuses",
            )
            db.execute("ROLLBACK")

        print("\nwhat can be stored")
        tag(db, ids["published"])
        tag(db, ids["draft"], tag_kind="feel", tag_slug="cosy", confidence="0.55")
        check(True, "the owner can write a well-formed tag")
        check(
            refuses(db, ids["published"], tag_kind="vibe"),
            "a kind the API does not know is refused",
        )
        check(
            refuses(db, ids["published"], tag_slug="Modern"),
            "a label instead of a slug is refused",
        )
        check(
            refuses(db, ids["published"], tag_slug="مودرن"),
            "a non-slug in any script is refused",
        )
        check(
            refuses(db, ids["published"], confidence="0"),
            "a zero confidence is refused",
        )
        check(
            refuses(db, ids["published"], confidence="1.5"),
            "a confidence above 1 is refused",
        )
        check(
            refuses(db, ids["published"], model_name="  "),
            "a tag with no named model is refused",
        )
        check(
            refuses(db, ids["published"]),
            "the same tag cannot be stored twice",
        )
        try:
            with db.transaction():
                db.execute(
                    "INSERT INTO public.product_search_tag "
                    "(product_id, tag_kind, tag_slug, confidence, model_name, source) "
                    "VALUES (%s, 'style', 'classic', 0.5, 'm', 'seller_stated')",
                    (ids["published"],),
                )
            check(False, "a tag cannot claim to be a seller's word")
        except psycopg.errors.CheckViolation:
            check(True, "a tag cannot claim to be a seller's word")

    @contextmanager
    def as_role(role: str) -> Iterator[psycopg.Connection]:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(f"SET ROLE {role}")
            yield connection

    print("\nwhat a client can do")
    for role in ("anon", "authenticated"):
        with as_role(role) as conn:
            visible = conn.execute(
                "SELECT product_id FROM public.product_search_tag"
            ).fetchall()
            check(
                [row[0] for row in visible] == [ids["published"]],
                f"{role} reads tags of published products only",
            )
            for statement, label in (
                (
                    "INSERT INTO public.product_search_tag "
                    "(product_id, tag_kind, tag_slug, confidence, model_name) "
                    f"VALUES ('{ids['published']}', 'feel', 'luxury', 0.9, 'x')",
                    "insert",
                ),
                (
                    "UPDATE public.product_search_tag SET confidence = 1",
                    "update",
                ),
                ("DELETE FROM public.product_search_tag", "delete"),
            ):
                try:
                    conn.execute(statement)
                    check(False, f"{role} cannot {label} a tag")
                except psycopg.errors.InsufficientPrivilege:
                    check(True, f"{role} cannot {label} a tag")

    print("\nlifecycle")
    with psycopg.connect(url, autocommit=True) as db:
        db.execute("DELETE FROM public.product WHERE id = %s", (ids["draft"],))
        left = db.execute(
            "SELECT count(*) FROM public.product_search_tag WHERE product_id = %s",
            (ids["draft"],),
        ).fetchone()[0]
        check(left == 0, "deleting a product takes its tags with it")

        results = db.execute(VERIFY.read_text(encoding="utf-8")).fetchall()
        check(
            len(results) == 9 and all(passed for _, passed in results),
            f"verification: {sum(1 for _, p in results if p)}/{len(results)}",
        )

        db.execute(UNDO.read_text(encoding="utf-8"))
        check(
            db.execute("SELECT to_regclass('public.product_search_tag')").fetchone()[0]
            is None,
            "the undo removes the table",
        )
        db.execute(UNDO.read_text(encoding="utf-8"))
        check(True, "the undo is safe to run twice")

        db.execute(MIGRATION.read_text(encoding="utf-8"))
        results = db.execute(VERIFY.read_text(encoding="utf-8")).fetchall()
        check(
            all(passed for _, passed in results),
            "the migration applies again after undo",
        )

    server.cleanup()
    print(f"\n{'PASSED' if not FAILURES else 'FAILED'}: {len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
