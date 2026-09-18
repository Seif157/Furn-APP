"""Round-trip the Phase 3.2D undo snapshot on a local PostgreSQL replica.

    uv run --no-project --python 3.12 --with pgserver --with "psycopg[binary]" \\
        --with pglast python scripts/replica_undo_32d_test.py

Builds 3.2D's 13 tables from the recorded columns, loads every live policy
recorded for them (docs/evidence/phase-3.2d/section-02-policies.csv) and a mix
of table and column grants, then:

  1. fingerprints every policy and grant on the 13 tables,
  2. runs the snapshot query and keeps the undo script it returns,
  3. changes the state the way 3.2D does: drops replaced policies, creates new
     phase32d_ policies, revokes and regrants table and column privileges,
     and creates functions with 3.2D's six exact signatures,
  4. runs the undo script,
  5. requires the fingerprint to equal step 1 and the six functions to be gone.

It also runs the snapshot a second time after step 3 and requires the script
it returns to refuse to run, because a snapshot taken after 3.2D is invalid.
"""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

import pgserver
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_32d_undo_snapshot import QUERY, SIGNATURES, TABLES  # noqa: E402

EVIDENCE = ROOT / "docs" / "evidence" / "phase-3.2d"
FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("  ok    " if condition else "  FAIL  ") + label)
    if not condition:
        FAILURES.append(label)


def rows(name: str) -> list[dict[str, str]]:
    with (EVIDENCE / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build(db: psycopg.Connection) -> int:
    for role in ("anon", "authenticated", "service_role"):
        db.execute(f"CREATE ROLE {role} NOLOGIN")
    db.execute("CREATE SCHEMA auth")
    db.execute(
        "CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$"
    )
    enums: dict[str, list[tuple[int, str]]] = {}
    for row in rows("state-enums.csv"):
        enums.setdefault(row["enum_type_name"], []).append(
            (int(row["label_order"]), row["label"])
        )
    for name, labels in enums.items():
        values = ", ".join(f"'{label}'" for _, label in sorted(labels))
        db.execute(f"CREATE TYPE public.{name} AS ENUM ({values})")

    # Every table the evidence describes, so policies can reference them.
    columns: dict[str, list[dict[str, str]]] = {}
    for row in rows("column-inventory.csv"):
        columns.setdefault(row["table_name"], []).append(row)
    for table, table_rows in columns.items():
        parts = []
        for r in sorted(table_rows, key=lambda r: int(r["ordinal_position"])):
            if r.get("generated_kind") == "s":
                parts.append(
                    f"{r['column_name']} {r['formatted_type']} GENERATED ALWAYS AS "
                    f"{r['default_expression']} STORED"
                )
            else:
                parts.append(f"{r['column_name']} {r['formatted_type']}")
        db.execute(f"CREATE TABLE public.{table} ({', '.join(parts)})")
    for table in ("product", "product_color", "category", "offer", "admin_user"):
        if table not in columns:
            db.execute(
                f"CREATE TABLE public.{table} (id uuid, product_id uuid, "
                "marketplace_party_id uuid, stock_quantity integer, "
                "lifecycle_state text, is_active boolean, user_id uuid)"
            )
    for helper, returns in (
        ("current_customer_profile_id", "uuid"),
        ("current_marketplace_party_id", "uuid"),
        ("is_admin", "boolean"),
        ("current_party_is_approved", "boolean"),
    ):
        db.execute(
            f"CREATE FUNCTION public.{helper}() RETURNS {returns} "
            f"LANGUAGE sql STABLE AS $$ SELECT NULL::{returns} $$"
        )
    for table in TABLES:
        db.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")

    loaded = 0
    for row in rows("section-02-policies.csv"):
        if row["table_name"] not in TABLES:
            continue
        roles = row["policy_roles"].strip("{}").replace('"', "")
        sql = (
            f"CREATE POLICY {row['policy_name']} ON public.{row['table_name']} "
            f"AS {row['policy_mode']} FOR {row['policy_command']} TO {roles}"
        )
        if row["complete_using_expression"] not in ("", "null"):
            sql += f" USING ({row['complete_using_expression']})"
        if row["complete_with_check_expression"] not in ("", "null"):
            sql += f" WITH CHECK ({row['complete_with_check_expression']})"
        try:
            db.execute(sql)
            loaded += 1
        except psycopg.Error as error:
            print(
                f"  (policy {row['policy_name']} skipped: {error.diag.message_primary})"
            )

    for table in TABLES:
        db.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO authenticated"
        )
        db.execute(f"GRANT ALL ON public.{table} TO service_role")
    db.execute("GRANT SELECT ON public.review TO anon")
    db.execute("GRANT SELECT (id, business_name) ON public.marketplace_party TO anon")
    db.execute("GRANT UPDATE (notes) ON public.purchase_order TO authenticated")
    return loaded


FINGERPRINT = f"""
SELECT
    (SELECT string_agg(
        format('%s|%s|%s|%s|%s|%s|%s', tablename, policyname, permissive,
               roles::text, cmd, coalesce(qual, '-'), coalesce(with_check, '-')),
        E'\\n' ORDER BY tablename, policyname)
     FROM pg_policies
     WHERE schemaname = 'public'
       AND tablename = ANY (ARRAY[{", ".join(f"'{t}'" for t in TABLES)}])),
    -- Privileges as sorted sets: PostgreSQL may reorder entries inside an ACL
    -- array after a revoke and regrant, which changes nothing about access.
    (SELECT string_agg(
        format('%s|%s|%s|%s', c.relname, acl.grantee::regrole, acl.privilege_type,
               acl.is_grantable),
        E'\\n' ORDER BY c.relname, acl.grantee::regrole::text, acl.privilege_type)
     FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) acl
     WHERE c.relnamespace = 'public'::regnamespace
       AND c.relname = ANY (ARRAY[{", ".join(f"'{t}'" for t in TABLES)}])),
    (SELECT string_agg(
        format('%s.%s|%s|%s|%s', c.relname, a.attname, acl.grantee::regrole,
               acl.privilege_type, acl.is_grantable),
        E'\\n' ORDER BY c.relname, a.attnum, acl.grantee::regrole::text,
                       acl.privilege_type)
     FROM pg_attribute a
     JOIN pg_class c ON c.oid = a.attrelid
     CROSS JOIN LATERAL aclexplode(a.attacl) acl
     WHERE c.relnamespace = 'public'::regnamespace
       AND c.relname = ANY (ARRAY[{", ".join(f"'{t}'" for t in TABLES)}])
       AND a.attnum > 0)
"""


def simulate_32d(db: psycopg.Connection) -> None:
    """The kinds of change 3.2D makes, on the same objects."""

    dropped = db.execute(
        "SELECT policyname, tablename FROM pg_policies WHERE schemaname = 'public' "
        "AND cmd = 'ALL' AND tablename = ANY (%s)",
        (list(TABLES),),
    ).fetchall()
    for policy, table in dropped:
        db.execute(f"DROP POLICY {policy} ON public.{table}")
    for table in TABLES:
        db.execute(
            f"CREATE POLICY phase32d_{table}_select_own ON public.{table} "
            "FOR SELECT TO authenticated USING (true)"
        )
        db.execute(f"REVOKE INSERT, UPDATE ON public.{table} FROM authenticated")
    db.execute("REVOKE SELECT ON public.marketplace_party FROM anon")
    db.execute(
        "GRANT SELECT (id, business_name, logo_url) ON public.marketplace_party TO anon"
    )
    db.execute("GRANT INSERT (quantity) ON public.cart_line TO authenticated")
    for signature in SIGNATURES:
        name, args = signature.split("(", 1)
        db.execute(
            f"CREATE FUNCTION {name}({args} RETURNS boolean LANGUAGE sql AS $$ SELECT true $$"
        )


def main() -> int:
    server = pgserver.get_server(
        tempfile.mkdtemp(prefix="furn-undo-"), cleanup_mode="delete"
    )
    with psycopg.connect(server.get_uri(), autocommit=True) as db:
        loaded = build(db)
        check(loaded >= 20, f"loaded {loaded} real policies on the 13 tables")
        before = db.execute(FINGERPRINT).fetchone()

        undo = db.execute(QUERY).fetchone()[0]
        check(
            "snapshot check: 3.2D not applied" in undo,
            "snapshot recognises 3.2D is not applied",
        )

        simulate_32d(db)
        changed = db.execute(FINGERPRINT).fetchone()
        check(changed != before, "the simulated 3.2D changed policies and grants")

        stale = db.execute(QUERY).fetchone()[0]
        try:
            db.execute(stale)
            check(False, "a snapshot taken after 3.2D refuses to run")
        except psycopg.errors.RaiseException:
            check(True, "a snapshot taken after 3.2D refuses to run")
            db.execute("ROLLBACK")

        db.execute(undo)
        after = db.execute(FINGERPRINT).fetchone()
        check(after[0] == before[0], "every policy restored exactly")
        check(after[1] == before[1], "every table grant restored exactly")
        if after[1] != before[1]:
            for old, new in zip(
                before[1].splitlines(), after[1].splitlines(), strict=True
            ):
                if old != new:
                    print(f"        before {old}\n        after  {new}")
        check(after[2] == before[2], "every column grant restored exactly")
        remaining = db.execute(
            "SELECT count(*) FROM pg_proc WHERE pronamespace = 'public'::regnamespace "
            "AND proname = ANY (%s)",
            ([s.split("(")[0].removeprefix("public.") for s in SIGNATURES],),
        ).fetchone()[0]
        check(remaining == 0, "the six 3.2D functions are gone")
    server.cleanup()
    print(f"\n{'PASSED' if not FAILURES else 'FAILED'}: {len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
