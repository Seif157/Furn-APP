"""Deterministic regression tests for the Phase 3.2B SQL package."""

import re
from pathlib import Path

import pytest
from pglast import ast, parse_sql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = PROJECT_ROOT / "sql"
AUDIT_PATH = SQL_DIR / "phase-3.2-rls-audit.sql"
MIGRATION_PATH = SQL_DIR / "phase-3.2b-security-hardening.sql"
VERIFY_PATH = SQL_DIR / "phase-3.2b-security-hardening-verify.sql"
HELPER_DIAGNOSTIC_PATH = SQL_DIR / "phase-3.2b-helper-function-definitions.sql"
MANAGED_DIAGNOSTIC_PATH = (
    SQL_DIR / "phase-3.2b-supabase-admin-default-privileges-diagnostic.sql"
)
MANAGED_MIGRATION_PATH = (
    SQL_DIR / "phase-3.2b-supabase-admin-default-privileges-optional.sql"
)
DOC_PATH = PROJECT_ROOT / "docs" / "phase-3.2b-security-hardening.md"

EXPECTED_TABLES = {
    "address",
    "admin_user",
    "cart",
    "cart_line",
    "category",
    "commission",
    "commission_reversal",
    "custom_offering",
    "customer_profile",
    "design",
    "design_product_reference",
    "design_version",
    "furnishing_request",
    "furnishing_request_design_version",
    "marketplace_party",
    "offer",
    "offer_line_item",
    "order_line_item",
    "party_capability",
    "payment",
    "platform_config",
    "product",
    "product_3d_model",
    "product_color",
    "product_enrichment_assignment",
    "product_enrichment_attribute",
    "product_image",
    "purchase_order",
    "refund",
    "review",
    "saved_space",
    "service_request",
    "service_type",
    "settlement",
}
ANON_SELECT_TABLES = {
    "category",
    "custom_offering",
    "marketplace_party",
    "party_capability",
    "product",
    "product_3d_model",
    "product_color",
    "product_enrichment_assignment",
    "product_enrichment_attribute",
    "product_image",
    "review",
    "service_type",
}
HELPER_FUNCTIONS = {
    "is_admin",
    "current_marketplace_party_id",
    "current_party_is_approved",
}
MIXED_POLICIES = {
    "custom_offering_select_published_or_own": "custom_offering",
    "product_select_published_or_own": "product",
    "product_color_select": "product_color",
    "product_image_select": "product_image",
    "product_3d_model_select": "product_3d_model",
    "product_enrichment_assignment_select": "product_enrichment_assignment",
}
CHILD_PREFIXES = (
    "product_color",
    "product_image",
    "product_3d_model",
    "enrichment",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalized(sql: str) -> str:
    return " ".join(sql.lower().split())


def numbered_section(sql: str, section: int, next_section: int) -> str:
    start = sql.index(f"-- {section:02d}.")
    end = sql.index(f"-- {next_section:02d}.", start)
    return sql[start:end]


def policy_definition(sql: str, policy_name: str) -> str:
    start = sql.index(f"create policy {policy_name}")
    return sql[start : sql.index(";", start)]


def alter_policy_definition(sql: str, policy_name: str) -> str:
    start = sql.index(f"alter policy {policy_name}")
    return sql[start : sql.index(";", start)]


def canonical_sql_source(source: str) -> str:
    return re.sub(r"\s", "", source.strip().rstrip(";").strip().lower())


def assert_complete_mixed_policy_alters(sql: str) -> None:
    for policy_name, table_name in MIXED_POLICIES.items():
        definition = alter_policy_definition(sql, policy_name)
        assert f"on public.{table_name}" in definition
        assert "to authenticated" in definition
        assert "using (" in definition
        assert "or true" not in definition
        assert "public.current_marketplace_party_id()" in definition
        assert "public.is_admin()" in definition
    assert "'published'::public.custom_offering_state" in alter_policy_definition(
        sql,
        "custom_offering_select_published_or_own",
    )
    for policy_name in set(MIXED_POLICIES) - {
        "custom_offering_select_published_or_own"
    }:
        assert "'published'::public.product_lifecycle_state" in (
            alter_policy_definition(sql, policy_name)
        )


def assert_read_only_sql(path: Path, *, expected_statements: int) -> None:
    statements = parse_sql(read(path))
    assert len(statements) == expected_statements
    assert all(isinstance(statement.stmt, ast.SelectStmt) for statement in statements)


def public_object_names(sql: str) -> set[str]:
    return set(re.findall(r"public\.([a-z][a-z0-9_]*)", sql))


def test_all_sql_files_parse_with_postgresql_parser() -> None:
    for path in SQL_DIR.glob("*.sql"):
        assert parse_sql(read(path)), path


def test_diagnostics_audit_and_verification_are_read_only() -> None:
    assert_read_only_sql(AUDIT_PATH, expected_statements=12)
    assert_read_only_sql(VERIFY_PATH, expected_statements=13)
    assert_read_only_sql(HELPER_DIAGNOSTIC_PATH, expected_statements=1)
    assert_read_only_sql(MANAGED_DIAGNOSTIC_PATH, expected_statements=1)


def test_only_explicit_migrations_contain_ddl_or_dcl_and_no_app_dml() -> None:
    mutation_paths = {MIGRATION_PATH, MANAGED_MIGRATION_PATH}
    for path in SQL_DIR.glob("*.sql"):
        statements = parse_sql(read(path))
        has_mutation = any(
            not isinstance(statement.stmt, ast.SelectStmt) for statement in statements
        )
        assert has_mutation is (path in mutation_paths), path

    for path in mutation_paths:
        assert not re.search(
            r"(?im)^\s*(insert\s+into|update\s+public\.|delete\s+from)\b",
            read(path),
        )


def test_audit_section_04_avoids_acl_array_expansion() -> None:
    section = normalized(numbered_section(read(AUDIT_PATH), 4, 5))
    assert "has_table_privilege" in section
    assert "has_column_privilege" in section
    assert "pg_catalog.pg_attribute" in section
    assert "aclexplode" not in section
    assert "array_agg" not in section


def test_core_migration_is_transactional_and_has_local_timeouts() -> None:
    sql = normalized(read(MIGRATION_PATH))
    assert sql.startswith("/* phase 3.2b")
    assert sql.endswith("commit;")
    begin = sql.index("begin;")
    preflight = sql.index("do $phase32b_preflight$")
    for safeguard in (
        "set local lock_timeout = '5s';",
        "set local statement_timeout = '5min';",
        "set local idle_in_transaction_session_timeout = '5min';",
    ):
        assert begin < sql.index(safeguard) < preflight
    assert "on all tables in schema" not in sql


def test_inventory_preflight_uses_order_independent_set_equality() -> None:
    sql = normalized(read(MIGRATION_PATH))
    start = sql.index("expected_tables constant text[] := array[")
    end = sql.index("];", start)
    assert set(re.findall(r"'([a-z][a-z0-9_]*)'", sql[start:end])) == EXPECTED_TABLES
    assert len(EXPECTED_TABLES) == 34
    assert "select table_name from expected except select table_name from actual" in sql
    assert "select table_name from actual except select table_name from expected" in sql
    assert "actual_tables is distinct from expected_tables" not in sql
    assert "missing=[%s]; unexpected=[%s]" in sql
    assert sql.index("missing=[%s]; unexpected=[%s]") < sql.index(
        "-- existing public base-table grants"
    )


def test_preflight_checks_exact_audited_metadata_before_changes() -> None:
    sql = normalized(read(MIGRATION_PATH))
    preflight = sql[: sql.index("-- existing public base-table grants")]
    for policy_name in MIXED_POLICIES:
        assert policy_name in preflight
    assert "actual_policy.polcmd <> 'r'::pg_catalog.\"char\"" in preflight
    assert "not actual_policy.polpermissive" in preflight
    assert "policy artifacts already exist" in preflight
    assert "marketplace_party table privilege drift" in preflight
    assert "financial view select grant drift" in preflight
    assert "helper definition or security metadata drift" in preflight
    assert "postgres default-acl namespace scope drift" in preflight
    assert "executor cannot perform postgres-owned core operations" in preflight


def test_existing_grants_are_explicit_and_public_is_not_a_transitive_bypass() -> None:
    sql = normalized(read(MIGRATION_PATH))
    grant_block = sql[
        sql.index("-- existing public base-table grants") : sql.index(
            "-- seller approval"
        )
    ]
    assert public_object_names(grant_block) == EXPECTED_TABLES
    assert "from public, anon" in grant_block
    assert "from authenticated" in grant_block
    assert "from public, anon, authenticated" in grant_block
    for privilege in (
        "insert",
        "update",
        "delete",
        "truncate",
        "references",
        "trigger",
        "maintain",
    ):
        assert privilege in grant_block


def test_anonymous_select_is_revoked_then_explicitly_regranted_to_allowlist() -> None:
    sql = normalized(read(MIGRATION_PATH))
    grant_match = re.search(r"grant select on table (?P<tables>.*?) to anon;", sql)
    assert grant_match
    assert public_object_names(grant_match.group("tables")) == ANON_SELECT_TABLES
    assert "revoke select" in sql[: grant_match.start()]
    assert "from public, anon" in sql[: grant_match.start()]
    assert len(ANON_SELECT_TABLES) == 12
    assert len(EXPECTED_TABLES - ANON_SELECT_TABLES) == 22


def test_marketplace_party_writes_are_fully_normalized() -> None:
    sql = normalized(read(MIGRATION_PATH))
    assert (
        "revoke insert, update on table public.marketplace_party from authenticated"
        in sql
    )
    all_columns = (
        "id, user_id, business_name, business_description, logo_url, coverage_area,"
        " approval_state, state_reason"
    )
    assert f"revoke insert ( {all_columns} )" in sql
    assert f"revoke update ( {all_columns} )" in sql
    assert (
        "grant insert ( user_id, business_name, business_description, logo_url,"
        " coverage_area ) on table public.marketplace_party to authenticated" in sql
    )
    assert (
        "grant update ( business_name, business_description, logo_url, coverage_area )"
        " on table public.marketplace_party to authenticated" in sql
    )
    assert "approval_state = ''pending''" in sql
    assert "state_reason is null" in sql


def test_verification_section_02_has_exact_insert_and_update_matrix() -> None:
    section = normalized(numbered_section(read(VERIFY_PATH), 2, 3))
    assert "table_insert_expected" in section
    assert "table_update_expected" in section
    assert "authenticated_insert_expected" in section
    assert "authenticated_update_expected" in section
    for column in (
        "id",
        "user_id",
        "business_name",
        "business_description",
        "logo_url",
        "coverage_area",
        "approval_state",
        "state_reason",
    ):
        assert f"'{column}'::name" in section
    assert "column_update_privilege_mismatch" in section
    assert "service_role" in section


def test_financial_view_is_preflighted_hardened_and_visibly_verified() -> None:
    migration = normalized(read(MIGRATION_PATH))
    verification = normalized(numbered_section(read(VERIFY_PATH), 4, 5))
    assert "financial view metadata or effective grant drift" in migration
    assert "financial view select grant drift" in migration
    assert (
        "revoke select on table public.order_financial_position from public, anon"
        in migration
    )
    assert (
        "alter view public.order_financial_position set (security_invoker = true)"
        in migration
    )
    for field in (
        "object_present",
        "expected_role",
        "actual_role",
        "expected_command",
        "actual_command",
        "finding_code",
    ):
        assert field in verification
    assert "left join actual_views" in verification


def test_policy_splitting_is_explicit_and_never_regex_generated() -> None:
    sql = normalized(read(MIGRATION_PATH))
    mutation_block = sql[
        sql.index("-- split only the six explicitly reviewed") : sql.index(
            "create policy phase32b_custom_offering_anon_read"
        )
    ]
    assert_complete_mixed_policy_alters(sql)
    assert "public_expression" not in sql
    assert "execute format( 'create policy" not in sql
    assert "phase32b_split_catalogue_owner_policies" not in sql
    assert "regexp_replace" not in mutation_block


def test_mixed_policy_validator_rejects_role_only_and_broadened_alters() -> None:
    sql = normalized(read(MIGRATION_PATH))
    assert_complete_mixed_policy_alters(sql)

    role_only = re.sub(
        r"(alter policy product_select_published_or_own .*?to authenticated)"
        r" using \(.*?\);",
        r"\1;",
        sql,
        count=1,
    )
    with pytest.raises(AssertionError):
        assert_complete_mixed_policy_alters(role_only)

    product_alter = alter_policy_definition(
        sql,
        "product_select_published_or_own",
    )
    broadened_alter = product_alter.replace(
        "lifecycle_state = 'published'::public.product_lifecycle_state",
        "lifecycle_state = 'published'::public.product_lifecycle_state or true",
        1,
    )
    broadened = sql.replace(product_alter, broadened_alter, 1)
    with pytest.raises(AssertionError):
        assert_complete_mixed_policy_alters(broadened)


def test_custom_offering_anonymous_predicate_is_explicitly_published() -> None:
    sql = normalized(read(MIGRATION_PATH))
    for name in (
        "phase32b_custom_offering_anon_read",
        "phase32b_custom_offering_anon_read_guard",
    ):
        definition = policy_definition(sql, name)
        assert (
            "publication_state = 'published'::public.custom_offering_state"
            in definition
        )
        assert not any(helper in definition for helper in HELPER_FUNCTIONS)
    preflight = sql[: sql.index("-- existing public base-table grants")]
    assert "expected_using_expression" in preflight
    assert "is distinct from pg_catalog.regexp_replace" in preflight


def test_anonymous_catalog_policies_never_call_restricted_helpers() -> None:
    sql = normalized(read(MIGRATION_PATH))
    anon_policy_names = (
        "phase32b_category_anon_read_guard",
        "phase32b_custom_offering_anon_read",
        "phase32b_custom_offering_anon_read_guard",
        "phase32b_product_anon_read",
        "phase32b_product_anon_read_guard",
        "phase32b_product_color_anon_read",
        "phase32b_product_color_anon_read_guard",
        "phase32b_product_image_anon_read",
        "phase32b_product_image_anon_read_guard",
        "phase32b_product_3d_model_anon_read",
        "phase32b_product_3d_model_anon_read_guard",
        "phase32b_enrichment_anon_read",
        "phase32b_enrichment_anon_read_guard",
    )
    for name in anon_policy_names:
        definition = policy_definition(sql, name)
        assert "to anon" in definition
        assert not any(helper in definition for helper in HELPER_FUNCTIONS)
    assert "anon-facing policy still depends on a restricted helper" in sql


def test_child_write_guards_constrain_sellers_without_claiming_admin_grants() -> None:
    sql = normalized(read(MIGRATION_PATH))
    child_start = sql.index("-- existing permissive seller policies")
    child_end = sql.index("-- fail before reducing function privileges", child_start)
    child_block = sql[child_start:child_end]
    assert "do not independently grant administrators" in child_block
    for prefix in CHILD_PREFIXES:
        for operation in ("insert", "update", "delete"):
            definition = policy_definition(
                sql,
                f"phase32b_{prefix}_{operation}_guard",
            )
            assert "as restrictive" in definition
            assert "public.current_party_is_approved()" in definition
            assert "public.current_marketplace_party_id()" in definition
            assert "public.is_admin()" not in definition
    preflight = sql[: sql.index("-- existing public base-table grants")]
    assert "missing permissive seller-write path" in preflight


def test_helpers_have_exact_preflight_and_hardened_definitions() -> None:
    sql = normalized(read(MIGRATION_PATH))
    preflight = sql[: sql.index("-- existing public base-table grants")]
    assert "expected_helper_source" in preflight
    assert "actual_helper_source is distinct from expected_helper_source" in preflight
    assert "'[[:space:]]', '', 'g'" in preflight
    assert sql.count("create or replace function public.") == 3
    assert sql.count("language sql stable security definer set search_path = ''") == 3
    assert "from public.admin_user as admin_row" in sql
    assert "from public.marketplace_party as party" in sql
    assert "'approved'::public.party_approval_state" in sql
    for name in HELPER_FUNCTIONS:
        assert f"revoke execute on function public.{name}() from public, anon" in sql
        assert (
            f"grant execute on function public.{name}() to authenticated, service_role"
            in sql
        )


def test_live_helper_body_fixtures_use_whitespace_only_canonical_equality() -> None:
    fixtures = {
        "is_admin": """
            SELECT EXISTS (
              SELECT 1
              FROM public.admin_user a
              WHERE a.user_id = auth.uid()
                AND a.is_active
            );
        """,
        "current_marketplace_party_id": """
            SELECT mp.id
            FROM public.marketplace_party mp
            WHERE mp.user_id = auth.uid();
        """,
        "current_party_is_approved": """
            SELECT EXISTS (
              SELECT 1
              FROM public.marketplace_party mp
              WHERE mp.user_id = auth.uid()
                AND mp.approval_state = 'approved'
            );
        """,
    }
    differently_spaced = {
        name: " \n\t".join(source.split()) for name, source in fixtures.items()
    }
    for name, source in fixtures.items():
        assert canonical_sql_source(source) == canonical_sql_source(
            differently_spaced[name]
        )

    inactive_removed = fixtures["is_admin"].replace("AND a.is_active", "")
    approved_removed = fixtures["current_party_is_approved"].replace(
        "AND mp.approval_state = 'approved'",
        "",
    )
    assert canonical_sql_source(inactive_removed) != canonical_sql_source(
        fixtures["is_admin"]
    )
    assert canonical_sql_source(approved_removed) != canonical_sql_source(
        fixtures["current_party_is_approved"]
    )


def test_verification_compares_complete_hardened_helper_sources() -> None:
    section = normalized(numbered_section(read(VERIFY_PATH), 7, 8))
    assert "complete_definition_matches" in section
    assert "function_row.prosrc" in section
    assert "expected.source_text" in section
    assert "admin_row.is_active" in section
    assert "party.approval_state" in section
    assert "'approved'::public.party_approval_state" in section


def test_core_default_changes_are_exactly_scoped_and_exclude_managed_role() -> None:
    sql = normalized(read(MIGRATION_PATH))
    assert "alter default privileges for role supabase_admin" not in sql
    assert (
        "alter default privileges for role postgres in schema public revoke all"
        " privileges on tables from public, anon, authenticated" in sql
    )
    assert (
        "alter default privileges for role postgres in schema public revoke all"
        " privileges on sequences from public, anon, authenticated" in sql
    )
    assert (
        "alter default privileges for role postgres in schema public revoke execute"
        " on functions from public, anon, authenticated" in sql
    )
    assert (
        "alter default privileges for role postgres revoke execute on functions"
        " from public, anon, authenticated" in sql
    )
    assert not re.search(
        r"alter default privileges for role postgres\s+revoke all privileges"
        r" on (tables|sequences)",
        sql,
    )
    assert "postgres default-acl namespace scope drift" in sql
    preflight = sql[: sql.index("-- existing public base-table grants")]
    assert "'f'::pg_catalog.\"char\", 'public'::name, 'anon'::name" in preflight
    assert "'f'::pg_catalog.\"char\", null::name" not in preflight


def test_managed_role_defaults_are_separate_diagnostic_and_optional_migration() -> None:
    diagnostic = normalized(read(MANAGED_DIAGNOSTIC_PATH))
    optional = normalized(read(MANAGED_MIGRATION_PATH))
    assert "pg_catalog.pg_default_acl" in diagnostic
    assert "can_alter_supabase_admin_defaults" in diagnostic
    assert "read only" in diagnostic
    assert "optional managed-role migration" in optional
    assert "not part of the core" in optional
    assert "scope has passed in staging" in optional
    assert "set local lock_timeout = '5s'" in optional
    assert (
        "alter default privileges for role supabase_admin in schema public" in optional
    )
    assert (
        "alter default privileges for role supabase_admin revoke execute on functions"
        in optional
    )
    assert (
        "alter default privileges for role supabase_admin in schema public revoke"
        " execute on functions from public, anon, authenticated" in optional
    )
    assert "phase32b_managed_defaults_postflight" in optional
    for scope_name in (
        "public_tables",
        "public_sequences",
        "public_functions",
        "global_functions",
    ):
        assert scope_name in diagnostic
        assert scope_name in optional


def test_catalog_codes_always_use_pg_catalog_internal_char() -> None:
    paths = tuple(SQL_DIR.glob("*.sql"))
    for path in paths:
        sql = read(path)
        assert not re.search(r"::\s*char\b", sql, re.IGNORECASE), path
        for match in re.finditer(r"acldefault\s*\(\s*'([rSf])'", sql):
            suffix = sql[match.end() : match.end() + 40]
            assert re.match(r"::\s*pg_catalog\.\"char\"", suffix), path


def test_core_has_fail_closed_transactional_postflight() -> None:
    sql = normalized(read(MIGRATION_PATH))
    start = sql.index("do $phase32b_postflight$")
    commit = sql.rindex("commit;")
    assert start < commit
    postflight = sql[start:commit]
    for invariant in (
        "34-table inventory or rls mismatch",
        "dangerous public or anon privilege remains",
        "anonymous select allowlist mismatch",
        "marketplace_party grant matrix mismatch",
        "seller insert policy mismatch",
        "financial view hardening mismatch",
        "exact mixed-policy mismatch",
        "expected read policy mismatch",
        "child write path mismatch",
        "helper mismatch",
        "anon helper dependency remains",
        "public_tables",
        "public_sequences",
        "public_functions",
        "global_functions",
    ):
        assert invariant in postflight
    assert "raise exception" in postflight


def test_verification_uses_four_effective_default_privilege_scopes() -> None:
    section = normalized(numbered_section(read(VERIFY_PATH), 11, 12))
    for scope_name in (
        "public_tables",
        "public_sequences",
        "public_functions",
        "global_functions",
    ):
        assert scope_name in section
    assert "pg_catalog.acldefault" in section
    assert "global_defaults.defaclacl" in section
    assert "schema_defaults.defaclacl" in section
    assert "missing_expected_postgres_default_acl" not in section


def test_verification_sections_03_through_06_fail_visibly() -> None:
    sql = normalized(read(VERIFY_PATH))
    for section_number in range(3, 7):
        section = numbered_section(sql, section_number, section_number + 1)
        assert "values" in section
        assert "left join" in section
        for field in (
            "object_present",
            "expected_role",
            "actual_role",
            "expected_command",
            "actual_command",
            "check_passed",
            "finding_code",
        ):
            assert field in section
    assert "duplicate_marketplace_party_insert_policy" in sql
    assert "custom_offering_state" in sql
    assert "missing_child_write_guard" in sql
    assert "missing_permissive_seller_write_policy" in sql


def test_verification_has_all_expected_read_and_write_policies() -> None:
    sql = normalized(read(VERIFY_PATH))
    for policy_name in MIXED_POLICIES:
        assert policy_name in sql
    for prefix in CHILD_PREFIXES:
        for operation in ("insert", "update", "delete"):
            assert f"phase32b_{prefix}_{operation}_guard" in sql
    assert "permissive_seller_policy_present" in sql
    assert "has_no_admin_grant_claim" in sql
    assert "anon_helper_dependency" in sql
    section = numbered_section(sql, 5, 6)
    assert "exact_mixed" in section
    assert "expected_using_expression" in section
    assert "is distinct from" not in section or "regexp_replace" in section
    assert "or true" not in section


def test_verification_has_one_row_per_section_summary() -> None:
    section = normalized(read(VERIFY_PATH).split("-- 13.", maxsplit=1)[1])
    for field in (
        "section_number",
        "expected_count",
        "actual_count",
        "failed_count",
        "check_passed",
    ):
        assert field in section
    for section_number in range(1, 13):
        assert f"'{section_number:02d}'::text" in section
    assert "('05'::text, 30::bigint)" in section
    assert "('06'::text, 12::bigint)" in section
    assert "('11'::text, 4::bigint)" in section


def test_documentation_corrects_admin_timeout_and_default_scope_claims() -> None:
    doc = normalized(read(DOC_PATH))
    assert "lock_timeout" in doc
    assert "rolls back" in doc
    assert "never" in doc and "increas" in doc
    assert "restrictive" in doc and "does not grant" in doc
    assert "supabase_admin" in doc
    assert "not fixed" in doc or "deferred" in doc
    assert "phase 3.2c" in doc


def test_security_artifacts_contain_no_secret_or_record_values() -> None:
    paths = (
        AUDIT_PATH,
        MIGRATION_PATH,
        VERIFY_PATH,
        HELPER_DIAGNOSTIC_PATH,
        MANAGED_DIAGNOSTIC_PATH,
        MANAGED_MIGRATION_PATH,
        DOC_PATH,
    )
    uuid_pattern = re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        re.IGNORECASE,
    )
    token_pattern = re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\b")

    for path in paths:
        content = read(path)
        assert not uuid_pattern.search(content), path
        assert not token_pattern.search(content), path
        assert "Bearer " not in content
        assert "access_token=" not in content
        assert "refresh_token=" not in content
        assert "SUPABASE_URL=" not in content
        assert "SUPABASE_PUBLISHABLE_KEY=" not in content
