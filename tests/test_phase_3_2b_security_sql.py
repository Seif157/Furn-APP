"""Deterministic regression tests for the Phase 3.2B SQL package."""

import re
from pathlib import Path

from pglast import ast, parse_sql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = PROJECT_ROOT / "sql"
AUDIT_PATH = SQL_DIR / "phase-3.2-rls-audit.sql"
MIGRATION_PATH = SQL_DIR / "phase-3.2b-security-hardening.sql"
VERIFY_PATH = SQL_DIR / "phase-3.2b-security-hardening-verify.sql"
HELPER_DIAGNOSTIC_PATH = SQL_DIR / "phase-3.2b-helper-function-definitions.sql"
DOC_PATH = PROJECT_ROOT / "docs" / "phase-3.2b-security-hardening.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalized(sql: str) -> str:
    return " ".join(sql.lower().split())


def numbered_section(sql: str, section: int, next_section: int) -> str:
    start = sql.index(f"-- {section:02d}.")
    end = sql.index(f"-- {next_section:02d}.", start)
    return sql[start:end]


def assert_read_only_sql(path: Path, *, expected_statements: int) -> None:
    statements = parse_sql(read(path))
    assert len(statements) == expected_statements
    assert all(isinstance(statement.stmt, ast.SelectStmt) for statement in statements)


def test_all_sql_files_parse_with_postgresql_parser() -> None:
    for path in SQL_DIR.glob("*.sql"):
        assert parse_sql(read(path)), path


def test_audit_and_diagnostic_sql_are_read_only() -> None:
    assert_read_only_sql(AUDIT_PATH, expected_statements=12)
    assert_read_only_sql(VERIFY_PATH, expected_statements=10)
    assert_read_only_sql(HELPER_DIAGNOSTIC_PATH, expected_statements=1)


def test_audit_section_04_avoids_acl_array_expansion() -> None:
    section = normalized(numbered_section(read(AUDIT_PATH), 4, 5))

    assert "has_table_privilege" in section
    assert "has_column_privilege" in section
    assert "pg_catalog.pg_attribute" in section
    assert "role_oid" in section
    assert "table_oid" in section
    assert "aclexplode" not in section
    assert "array_agg" not in section
    assert "array_cat" not in section


def test_migration_is_transactional_and_fail_closed_until_allowlist_exists() -> None:
    sql = read(MIGRATION_PATH)
    compact = normalized(sql)

    assert compact.startswith("/* phase 3.2b")
    assert "begin;" in compact
    assert compact.endswith("commit;")
    assert "phase32b_reviewed_table_list_required" in sql
    assert "reviewed 34-table and anon-SELECT lists" in sql
    assert "REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA" not in sql
    assert sql.index("phase32b_reviewed_table_list_required") < sql.index(
        "-- Seller approval"
    )


def test_marketplace_party_approval_is_protected_by_grants_and_rls() -> None:
    sql = normalized(read(MIGRATION_PATH))

    assert "revoke insert on table public.marketplace_party from authenticated" in sql
    assert "grant insert ( user_id, business_name, business_description," in sql
    assert "logo_url, coverage_area ) on table public.marketplace_party" in sql
    assert "revoke insert (id, approval_state, state_reason)" in sql
    assert "user_id = (select auth.uid())" in sql
    assert "approval_state = ''pending''" in sql
    assert "state_reason is null" in sql
    assert "requires the generated marketplace_party.id default" in sql
    assert "grant update" not in sql


def test_financial_view_uses_invoker_rights_and_blocks_anonymous_reads() -> None:
    sql = normalized(read(MIGRATION_PATH))

    assert (
        "revoke select on table public.order_financial_position from public, anon"
        in sql
    )
    assert (
        "alter view public.order_financial_position set (security_invoker = true)"
        in sql
    )
    assert (
        "grant select on table public.order_financial_position to authenticated,"
        " service_role" in sql
    )


def test_catalogue_read_guards_preserve_public_owner_and_admin_paths() -> None:
    sql = normalized(read(MIGRATION_PATH))

    assert "phase32b_category_anon_read_guard" in sql
    assert "phase32b_category_authenticated_read_guard" in sql
    assert "is_active = true" in sql
    assert "phase32b_product_owner_read" in sql
    assert "phase32b_product_anon_read_guard" in sql
    assert "phase32b_product_authenticated_read_guard" in sql
    assert "lifecycle_state = 'published'" in sql
    assert "seller.approval_state = 'approved'" in sql
    assert "product_category.is_active = true" in sql
    assert "marketplace_party_id = public.current_marketplace_party_id()" in sql
    assert "or public.is_admin()" in sql
    assert "confirmation_state = 'party_confirmed'" in sql

    product_section = sql.split("-- product reads:", maxsplit=1)[1].split(
        "-- child reads", maxsplit=1
    )[0]
    assert "product_color" not in product_section
    assert "product_image" not in product_section
    assert "product_3d_model" not in product_section
    assert "product_enrichment_assignment" not in product_section


def test_all_catalogue_children_have_read_and_approved_write_guards() -> None:
    sql = normalized(read(MIGRATION_PATH))
    policy_prefixes = (
        "product_color",
        "product_image",
        "product_3d_model",
        "enrichment",
    )

    for prefix in policy_prefixes:
        assert f"phase32b_{prefix}_owner_read" in sql
        for operation in ("insert", "update", "delete"):
            policy_name = f"phase32b_{prefix}_{operation}_guard"
            start = sql.index(f"create policy {policy_name}")
            end = sql.find("drop policy", start)
            policy_sql = sql[start:] if end == -1 else sql[start:end]
            assert "as restrictive" in policy_sql
            assert "to authenticated" in policy_sql
            assert "public.current_party_is_approved()" in policy_sql
            assert "public.current_marketplace_party_id()" in policy_sql
            assert "public.is_admin()" in policy_sql

    for prefix in ("product_color", "product_image", "product_3d_model"):
        assert f"phase32b_{prefix}_read_guard" in sql
    assert "phase32b_enrichment_anon_read_guard" in sql
    assert "phase32b_enrichment_authenticated_read_guard" in sql


def test_future_default_privileges_are_hardened_for_both_owner_roles() -> None:
    sql = normalized(read(MIGRATION_PATH))

    for owner in ("postgres", "supabase_admin"):
        prefix = f"alter default privileges for role {owner} in schema public"
        assert (
            f"{prefix} revoke all privileges on tables from public, anon,"
            " authenticated" in sql
        )
        assert (
            f"{prefix} revoke all privileges on sequences from public, anon,"
            " authenticated" in sql
        )
        assert (
            f"{prefix} revoke execute on functions from public, anon, authenticated"
            in sql
        )


def test_missing_helper_bodies_are_diagnosed_not_invented() -> None:
    migration = normalized(read(MIGRATION_PATH))
    diagnostic = normalized(read(HELPER_DIAGNOSTIC_PATH))

    assert "create function" not in migration
    assert "create or replace function" not in migration
    assert "alter function" not in migration
    assert "revoke execute on function public." not in migration
    assert "pg_catalog.pg_get_functiondef" in diagnostic
    for function_name in (
        "is_admin",
        "current_marketplace_party_id",
        "current_party_is_approved",
    ):
        assert function_name in diagnostic


def test_verification_covers_every_required_security_invariant() -> None:
    sql = normalized(read(VERIFY_PATH))

    assert "rls_enabled" in sql
    assert "authenticated_insert_expected" in sql
    assert "enforces_pending_state" in sql
    assert "security_invoker" in sql
    assert "phase32b_product_anon_read_guard" in sql
    assert "phase32b_enrichment_anon_read_guard" in sql
    assert "current_party_is_approved" in sql
    assert "hardened_check_passed" in sql
    assert "dangerous existing grants" in sql
    assert "unsafe automatic grants" in sql
    assert "unexpectedly lose every policy" in sql


def test_security_artifacts_contain_no_secret_or_record_values() -> None:
    paths = (
        AUDIT_PATH,
        MIGRATION_PATH,
        VERIFY_PATH,
        HELPER_DIAGNOSTIC_PATH,
        DOC_PATH,
    )
    uuid_pattern = re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        re.IGNORECASE,
    )

    for path in paths:
        content = read(path)
        assert "Bearer " not in content
        assert "access_token" not in content
        assert "refresh_token" not in content
        assert "SUPABASE_URL=" not in content
        assert "SUPABASE_PUBLISHABLE_KEY=" not in content
        assert not uuid_pattern.search(content)
