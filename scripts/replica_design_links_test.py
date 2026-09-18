"""Execute the design-version-links migration against a local PostgreSQL replica.

    uv run --no-project --python 3.12 --with pgserver --with "psycopg[binary]" \\
        python scripts/replica_design_links_test.py

Rebuilds the six tables involved from the recorded live columns, enums and
constraints, recreates the post-3.2D state of furnishing_request_design_version
(no client INSERT or UPDATE, 3.2D's own delete policy taken verbatim from the
3.2D migration), applies migrations/design-version-links-2026-09-19.sql as the
owner will, and then acts as signed-in customers with row-level security
enforced, the way the app will. Nothing touches Supabase.
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
EVIDENCE = ROOT / "docs" / "evidence" / "phase-3.2d"
MIGRATION = ROOT / "migrations" / "design-version-links-2026-09-19.sql"
UNDO = ROOT / "migrations" / "design-version-links-2026-09-19-undo.sql"
VERIFY = ROOT / "migrations" / "design-version-links-2026-09-19-verify.sql"
PHASE_32D = ROOT / "sql" / "phase-3.2d-security-hardening.sql"
TABLES = (
    "customer_profile",
    "address",
    "furnishing_request",
    "design",
    "design_version",
    "furnishing_request_design_version",
)
FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("  ok    " if condition else "  FAIL  ") + label)
    if not condition:
        FAILURES.append(label)


def rows(name: str) -> list[dict[str, str]]:
    with (EVIDENCE / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build(db: psycopg.Connection) -> None:
    for role in ("anon", "authenticated", "service_role"):
        db.execute(f"CREATE ROLE {role} NOLOGIN")
    db.execute("CREATE SCHEMA auth")
    db.execute(
        "CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$"
    )
    db.execute("GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role")
    db.execute(
        "GRANT EXECUTE ON FUNCTION auth.uid() TO anon, authenticated, service_role"
    )
    enums: dict[str, list[tuple[int, str]]] = {}
    for row in rows("state-enums.csv"):
        enums.setdefault(row["enum_type_name"], []).append(
            (int(row["label_order"]), row["label"])
        )
    for name, labels in enums.items():
        values = ", ".join(f"'{label}'" for _, label in sorted(labels))
        db.execute(f"CREATE TYPE public.{name} AS ENUM ({values})")

    columns: dict[str, list[dict[str, str]]] = {t: [] for t in TABLES}
    for row in rows("column-inventory.csv"):
        if row["table_name"] in columns:
            columns[row["table_name"]].append(row)
    for table in TABLES:
        parts = []
        for r in sorted(columns[table], key=lambda r: int(r["ordinal_position"])):
            spec = f"{r['column_name']} {r['formatted_type']}"
            if r["default_expression"] not in ("", "null"):
                spec += f" DEFAULT {r['default_expression']}"
            if r["is_not_null"] == "true":
                spec += " NOT NULL"
            parts.append(spec)
        db.execute(f"CREATE TABLE public.{table} ({', '.join(parts)})")

    constraints = [r for r in rows("constraints.csv") if r["table_name"] in TABLES]
    for row in constraints:  # keys and checks first, so foreign keys can refer to them
        if row["constraint_kind"] != "f":
            db.execute(
                f"ALTER TABLE public.{row['table_name']} "
                f"ADD CONSTRAINT {row['constraint_name']} {row['definition']}"
            )
    for table in TABLES:
        has_pk = db.execute(
            "SELECT 1 FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'p'",
            (f"public.{table}",),
        ).fetchone()
        if not has_pk:
            db.execute(f"ALTER TABLE public.{table} ADD PRIMARY KEY (id)")
    for row in constraints:
        if (
            row["constraint_kind"] == "f"
            and (row.get("referenced_table") or "") in TABLES
        ):
            db.execute(
                f"ALTER TABLE public.{row['table_name']} "
                f"ADD CONSTRAINT {row['constraint_name']} {row['definition']}"
            )

    db.execute(
        "CREATE FUNCTION public.current_customer_profile_id() RETURNS uuid "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS "
        "$$ SELECT id FROM public.customer_profile WHERE user_id = auth.uid() $$"
    )
    db.execute(
        "GRANT EXECUTE ON FUNCTION public.current_customer_profile_id() TO authenticated"
    )
    for table in TABLES:
        db.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")

    # The post-3.2D state of the link table: read and delete, never write.
    db.execute(
        "GRANT SELECT, DELETE ON public.furnishing_request_design_version TO authenticated"
    )
    db.execute("GRANT SELECT ON public.furnishing_request TO authenticated")
    db.execute(
        "CREATE POLICY own_requests ON public.furnishing_request FOR SELECT "
        "TO authenticated USING (customer_profile_id = public.current_customer_profile_id())"
    )
    db.execute(
        "CREATE POLICY own_links ON public.furnishing_request_design_version FOR SELECT "
        "TO authenticated USING (EXISTS (SELECT 1 FROM public.furnishing_request r "
        "WHERE r.id = furnishing_request_id "
        "AND r.customer_profile_id = public.current_customer_profile_id()))"
    )
    text = PHASE_32D.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = text.index(
        "CREATE POLICY phase32d_furnishing_request_design_version_delete_own"
    )
    end = text.index(");\n", start) + 2
    db.execute(text[start:end])


def main() -> int:
    server = pgserver.get_server(
        tempfile.mkdtemp(prefix="furn-links-"), cleanup_mode="delete"
    )
    url = server.get_uri()
    ids = {
        k: uuid.uuid4()
        for k in (
            "user_a",
            "user_b",
            "profile_a",
            "profile_b",
            "address_a",
            "address_b",
            "req_draft",
            "req_open",
            "req_accepted",
            "req_b",
            "design_a",
            "design_b",
            "version_a",
            "version_a2",
            "version_b",
        )
    }

    with psycopg.connect(url, autocommit=True) as db:
        build(db)
        db.execute(MIGRATION.read_text(encoding="utf-8"))
        print("replica built; migration applied\n")
        try:
            db.execute(MIGRATION.read_text(encoding="utf-8"))
            check(False, "a second run refuses")
        except psycopg.errors.RaiseException as error:
            check(
                "already applied" in error.diag.message_primary, "a second run refuses"
            )
            db.execute("ROLLBACK")

        db.execute(
            "INSERT INTO customer_profile (id, user_id, full_name) VALUES (%s, %s, 'A'), (%s, %s, 'B')",
            (ids["profile_a"], ids["user_a"], ids["profile_b"], ids["user_b"]),
        )
        db.execute(
            "INSERT INTO address (id, customer_profile_id, recipient_name, contact_phone, address_line_1, city, country) "
            "VALUES (%s, %s, 'A', '1', 'x', 'Cairo', 'EG'), (%s, %s, 'B', '2', 'y', 'Giza', 'EG')",
            (ids["address_a"], ids["profile_a"], ids["address_b"], ids["profile_b"]),
        )
        for key, profile, address, state in (
            ("req_draft", "profile_a", "address_a", "draft"),
            ("req_open", "profile_a", "address_a", "open"),
            ("req_accepted", "profile_a", "address_a", "accepted"),
            ("req_b", "profile_b", "address_b", "draft"),
        ):
            db.execute(
                "INSERT INTO furnishing_request (id, customer_profile_id, address_id, title, "
                "requirements_description, lifecycle_state) VALUES (%s, %s, %s, 't', 'd', %s)",
                (ids[key], ids[profile], ids[address], state),
            )
        db.execute(
            "INSERT INTO design (id, originating_user_id) VALUES (%s, %s), (%s, %s)",
            (ids["design_a"], ids["user_a"], ids["design_b"], ids["user_b"]),
        )
        for key, design, sequence in (
            ("version_a", "design_a", 1),
            ("version_a2", "design_a", 2),
            ("version_b", "design_b", 1),
        ):
            db.execute(
                "INSERT INTO design_version (id, design_id, version_sequence, generated_image_url, "
                "requested_attributes) VALUES (%s, %s, %s, 'https://x/y.png', '{}')",
                (ids[key], ids[design], sequence),
            )

    def as_user(user: str | None, role: str = "authenticated") -> psycopg.Connection:
        conn = psycopg.connect(url, autocommit=True)
        conn.execute(f"SET ROLE {role}")
        if user:
            conn.execute(
                "SELECT set_config('request.jwt.claim.sub', %s, false)",
                (str(ids[user]),),
            )
        return conn

    insert = "INSERT INTO furnishing_request_design_version (furnishing_request_id, design_version_id) VALUES (%s, %s)"

    def attempt(user, request, version, role="authenticated") -> str:
        with as_user(user, role) as conn:
            try:
                conn.execute(insert, (ids[request], ids[version]))
                return "allowed"
            except psycopg.errors.InsufficientPrivilege as error:
                return "denied: " + error.diag.message_primary.split(" for ")[0]

    print("\nattaching")
    check(
        attempt("user_a", "req_draft", "version_a") == "allowed",
        "own design to own draft request",
    )
    check(
        attempt("user_a", "req_open", "version_a2") == "allowed",
        "own design to own open request",
    )
    check(
        attempt("user_a", "req_accepted", "version_a").startswith("denied"),
        "refused once the request is accepted",
    )
    check(
        attempt("user_a", "req_b", "version_a").startswith("denied"),
        "refused on someone else's request",
    )
    check(
        attempt("user_a", "req_draft", "version_b").startswith("denied"),
        "refused for someone else's design",
    )
    check(
        attempt(None, "req_draft", "version_a2", "anon").startswith("denied"),
        "refused for anonymous visitors",
    )

    print("\nafter attaching")
    with as_user("user_a") as conn:
        try:
            conn.execute(
                "UPDATE furnishing_request_design_version SET design_version_id = %s "
                "WHERE furnishing_request_id = %s",
                (ids["version_a2"], ids["req_draft"]),
            )
            check(False, "links cannot be updated")
        except psycopg.errors.InsufficientPrivilege:
            check(True, "links cannot be updated")
        deleted = conn.execute(
            "DELETE FROM furnishing_request_design_version WHERE furnishing_request_id = %s",
            (ids["req_draft"],),
        ).rowcount
        check(deleted == 1, "the 3.2D rule still lets the owner delete while draft")
    with as_user(None, "anon") as conn:
        try:
            conn.execute(
                "SELECT public.can_attach_design_version(%s, %s)",
                (ids["req_draft"], ids["version_a"]),
            )
            check(False, "anonymous visitors cannot call the helper")
        except psycopg.errors.InsufficientPrivilege:
            check(True, "anonymous visitors cannot call the helper")

    print("\nverification, undo, re-apply")
    with psycopg.connect(url, autocommit=True) as db:
        results = db.execute(VERIFY.read_text(encoding="utf-8")).fetchall()
        check(
            len(results) == 6 and all(p for _, p in results),
            f"verification: {sum(p for _, p in results)}/{len(results)}",
        )
        db.execute(UNDO.read_text(encoding="utf-8"))
    check(
        attempt("user_a", "req_draft", "version_a").startswith("denied"),
        "after undo, attaching is refused again",
    )
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(MIGRATION.read_text(encoding="utf-8"))
        results = db.execute(VERIFY.read_text(encoding="utf-8")).fetchall()
        check(all(p for _, p in results), "the migration applies again after undo")
    check(
        attempt("user_a", "req_draft", "version_a") == "allowed",
        "and attaching works again",
    )

    server.cleanup()
    print(f"\n{'PASSED' if not FAILURES else 'FAILED'}: {len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
