"""Deterministic regression tests for the Phase 3.2B SQL package."""

import re
from pathlib import Path

import pytest
from pglast import ast, parse_sql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = PROJECT_ROOT / "sql"
AUDIT_PATH = SQL_DIR / "phase-3.2-rls-audit.sql"
MIGRATION_PATH = SQL_DIR / "phase-3.2b-security-hardening.sql"
PREFLIGHT_PATH = SQL_DIR / "phase-3.2b-security-hardening-preflight.sql"
VERIFY_PATH = SQL_DIR / "phase-3.2b-security-hardening-verify.sql"
HELPER_DIAGNOSTIC_PATH = SQL_DIR / "phase-3.2b-helper-function-definitions.sql"
MANAGED_DIAGNOSTIC_PATH = (
    SQL_DIR / "phase-3.2b-supabase-admin-default-privileges-diagnostic.sql"
)
MANAGED_MIGRATION_PATH = (
    SQL_DIR / "phase-3.2b-supabase-admin-default-privileges-optional.sql"
)
DOC_PATH = PROJECT_ROOT / "docs" / "phase-3.2b-security-hardening.md"
AUDIT_DOC_PATH = PROJECT_ROOT / "docs" / "phase-3.2-rls-audit.md"

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
MIXED_POLICY_CANONICAL_EXPRESSIONS = {
    "custom_offering_select_published_or_own": (
        "publication_state='published'::custom_offering_stateor"
        "marketplace_party_id=current_marketplace_party_id"
    ),
    "product_select_published_or_own": (
        "lifecycle_state='published'::product_stateor"
        "marketplace_party_id=current_marketplace_party_id"
    ),
    "product_color_select": (
        "existsselect1fromproductwhereid=product_idand"
        "lifecycle_state='published'::product_stateor"
        "marketplace_party_id=current_marketplace_party_id"
    ),
    "product_image_select": (
        "existsselect1fromproductwhereid=product_idand"
        "lifecycle_state='published'::product_stateor"
        "marketplace_party_id=current_marketplace_party_id"
    ),
    "product_3d_model_select": (
        "existsselect1fromproductwhereid=product_idand"
        "lifecycle_state='published'::product_stateor"
        "marketplace_party_id=current_marketplace_party_id"
    ),
    "product_enrichment_assignment_select": (
        "existsselect1fromproductwhereid=product_idand"
        "lifecycle_state='published'::product_stateor"
        "marketplace_party_id=current_marketplace_party_id"
    ),
}
CHILD_PREFIXES = (
    "product_color",
    "product_image",
    "product_3d_model",
    "enrichment",
)
STORAGE_PRIVILEGES = {
    ("r", "SELECT"),
    ("r", "INSERT"),
    ("r", "UPDATE"),
    ("r", "DELETE"),
    ("r", "TRUNCATE"),
    ("r", "REFERENCES"),
    ("r", "TRIGGER"),
    ("r", "MAINTAIN"),
    ("S", "SELECT"),
    ("S", "UPDATE"),
    ("S", "USAGE"),
    ("f", "EXECUTE"),
}
CLIENT_ROLES = {"anon", "authenticated"}
MANAGED_ELEVATED_SERVER_ROLES = {"service_role"}
EXPECTED_STORAGE_ROLES = CLIENT_ROLES | MANAGED_ELEVATED_SERVER_ROLES


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


def using_expression(definition: str) -> str:
    marker = "using ("
    opening = definition.index(marker) + len("using ")
    depth = 0
    in_string = False
    index = opening
    while index < len(definition):
        character = definition[index]
        if character == "'":
            if in_string and index + 1 < len(definition):
                if definition[index + 1] == "'":
                    index += 2
                    continue
            in_string = not in_string
        elif not in_string and character == "(":
            depth += 1
        elif not in_string and character == ")":
            depth -= 1
            if depth == 0:
                return definition[opening + 1 : index]
        index += 1
    raise AssertionError("unterminated ALTER POLICY USING expression")


def canonical_policy_expression(expression: str) -> str:
    reconstructed = re.sub(
        r"from\s+(?:public\.)?product(?:\s+as)?\s+[a-z_][a-z0-9_]*\s+where",
        "from product where",
        expression.lower(),
    )
    unqualified = re.sub(r"\b[a-z_][a-z0-9_]*\.", "", reconstructed)
    return re.sub(r"[\s()]", "", unqualified)


def operator_depth(expression: str, operator: str) -> tuple[int, int]:
    position = expression.find(f" {operator} ")
    if position < 0:
        return position, 0
    prefix = expression[:position]
    return position, prefix.count("(") - prefix.count(")")


def assert_complete_mixed_policy_alters(sql: str) -> None:
    for policy_name, table_name in MIXED_POLICIES.items():
        definition = alter_policy_definition(sql, policy_name)
        assert f"on public.{table_name}" in definition
        assert "to authenticated" in definition
        assert "using (" in definition
        assert "or true" not in definition
        assert "public.current_marketplace_party_id()" in definition
        assert "public.is_admin()" not in definition
        assert "with check" not in definition
        expression = using_expression(definition)
        assert (
            canonical_policy_expression(expression)
            == (MIXED_POLICY_CANONICAL_EXPRESSIONS[policy_name])
        )
        normalized_expression = normalized(expression)
        and_position, and_depth = operator_depth(normalized_expression, "and")
        or_position, or_depth = operator_depth(normalized_expression, "or")
        if policy_name in {
            "custom_offering_select_published_or_own",
            "product_select_published_or_own",
        }:
            assert and_position < 0
            assert or_position >= 0
        else:
            assert "from public.product as p" in definition
            assert and_position >= 0
            assert or_position >= 0
            assert or_depth > and_depth


def preflight_do_block(sql: str) -> str:
    start = sql.index("DO $phase32b_preflight$")
    tag = "$phase32b_preflight$;"
    return sql[start : sql.index(tag, start) + len(tag)]


def assert_no_handcrafted_policy_expression_equality(sql: str) -> None:
    assert "expected_using_expression" not in canonical_sql_source(sql)
    expression_source = (
        r"(?:actual_policy\.using_expr|policy_row\.using_expr|actual\.qual|"
        r"policy\.qual|(?:pg_catalog\.)?pg_get_expr\b)"
    )
    whitespace_only_comparison = re.compile(
        r"regexp_replace\s*\(\s*lower\s*\(\s*"
        + expression_source
        + r"[^;]{0,300}?\)\s*,\s*'\[\[:space:\]\]\+?'\s*,\s*"
        r"(?:''|' ')\s*,\s*'g'\s*\)\s*(?:=|is\s+distinct\s+from)",
        re.IGNORECASE,
    )
    assert not whitespace_only_comparison.search(sql)


def assert_authenticated_dangerous_postflight(sql: str) -> None:
    postflight = sql[sql.index("do $phase32b_postflight$") :]
    required = (
        "or exists ( select 1 from pg_catalog.pg_class as relation where "
        "relation.relnamespace = 'public'::regnamespace and relation.relkind "
        "in ('r', 'p') and pg_catalog.has_table_privilege( "
        "authenticated_role_oid, relation.oid, "
        "'truncate, references, trigger' ) ) then"
    )
    assert required in postflight


def assert_sequence_acl_codes(sql: str) -> None:
    assert not re.search(
        r"acldefault\s*\(\s*'S'::\s*pg_catalog\.\"char\"",
        sql,
    )
    assert not re.search(
        r"acldefault\s*\(\s*expected\."
        r"(?:object_type(?:_code)?|catalog_object_type(?:_code)?)",
        sql,
        re.IGNORECASE,
    )
    sequence_positions = [
        match.start() for match in re.finditer("'public_sequences'", sql)
    ]
    assert sequence_positions
    for start in sequence_positions:
        end = sql.find("'public_functions'", start)
        sequence_mapping = sql[start:end]
        assert "'S'::pg_catalog.\"char\"" in sequence_mapping
        assert "'s'::pg_catalog.\"char\"" in sequence_mapping


def assert_no_child_admin_access(sql: str) -> None:
    child_owner_policies = (
        "phase32b_product_color_owner_read",
        "phase32b_product_image_owner_read",
        "phase32b_product_3d_model_owner_read",
        "phase32b_enrichment_owner_read",
    )
    child_mixed_policies = set(MIXED_POLICIES) - {
        "custom_offering_select_published_or_own",
        "product_select_published_or_own",
    }
    for policy_name in child_owner_policies:
        definition = policy_definition(sql, policy_name)
        assert "public.current_marketplace_party_id()" in definition
        assert "public.is_admin()" not in definition
    for policy_name in child_mixed_policies:
        definition = alter_policy_definition(sql, policy_name)
        assert "public.current_marketplace_party_id()" in definition
        assert "public.is_admin()" not in definition


def expected_storage_signature(*, include_maintain: bool) -> set[tuple[object, ...]]:
    privileges = STORAGE_PRIVILEGES
    if not include_maintain:
        privileges = privileges - {("r", "MAINTAIN")}
    return {
        ("postgres", "storage", object_type, grantee, privilege, False)
        for grantee in EXPECTED_STORAGE_ROLES
        for object_type, privilege in privileges
    }


def reviewed_postgres_role_default_scope(
    schema_name: str,
    object_type: str,
) -> bool:
    return (
        schema_name in {"public", "storage"} and object_type in {"r", "S", "f"}
    ) or (schema_name == "<all_schemas>" and object_type == "f")


def assert_storage_signature_guards(sql: str, *, expected_blocks: int) -> None:
    normalized_sql = normalized(sql)
    reviewed_scope_clause = (
        "and not ( ( namespace.nspname in ('public', 'storage') and "
        "defaults.defaclobjtype in ( 'r'::pg_catalog.\"char\", "
        "'s'::pg_catalog.\"char\", 'f'::pg_catalog.\"char\" ) ) or ( "
        "defaults.defaclnamespace = 0 and defaults.defaclobjtype = "
        "'f'::pg_catalog.\"char\" ) ) ) then"
    )
    block_starts = [
        match.start() for match in re.finditer(r"\bexpected_storage_signature\(", sql)
    ]
    assert len(block_starts) == expected_blocks
    for start in block_starts:
        end = sql.index("actual_storage_signature AS", start)
        block = sql[start:end]
        observed_privileges = set(
            re.findall(
                r"\('([rSf])'::pg_catalog\.\"char\", '([A-Z]+)'::text\)",
                block,
            )
        )
        assert observed_privileges == STORAGE_PRIVILEGES
        observed_grantees = set(re.findall(r"\('([a-z_]+)'::name\)", block))
        assert observed_grantees == EXPECTED_STORAGE_ROLES
        assert "'postgres'::name" in block
        assert "'storage'::name" in block
        assert "false" in block
        assert "privilege.privilege_type <> 'MAINTAIN'" in block
        assert "current_setting('server_version_num')::integer >= 170000" in block

        actual_end_candidates = (
            sql.find("\n    ),\n    missing AS (", end),
            sql.find("\n        )\n        (", end),
        )
        actual_block_end = min(
            position for position in actual_end_candidates if position >= 0
        )
        actual_block = normalized(sql[end:actual_block_end])
        for identity_field in (
            "owner_role.rolname as owner_name",
            "namespace.nspname as schema_name",
            "defaults.defaclobjtype as object_type",
            "'public'::name",
            "grantee_role.rolname",
            "acl.privilege_type",
            "acl.is_grantable",
            "namespace.nspname = 'storage'",
            "acl.grantee <> defaults.defaclrole",
        ):
            assert identity_field in actual_block
        assert "grantee_role.rolname in" not in actual_block
        assert "acl.grantee in" not in actual_block

        comparison_end = sql.find("END IF;", end)
        comparison = normalized(sql[end:comparison_end])
        assert (
            "select * from expected_storage_signature except select * from "
            "actual_storage_signature" in comparison
        )
        assert (
            "select * from actual_storage_signature except select * from "
            "expected_storage_signature" in comparison
        )

        effective_check_end = sql.find(
            "managed storage function default EXECUTE is not effective",
            comparison_end,
        )
        effective_check = normalized(sql[comparison_end:effective_check_end])
        assert "(anon_role_oid)" in effective_check
        assert "(authenticated_role_oid)" in effective_check
        assert "(service_role_oid)" in effective_check
        assert "as managed_storage_role(role_oid)" in effective_check
        assert "as client(role_oid)" not in effective_check
        assert (
            "grantee_role.rolname in ( 'anon', 'authenticated', 'service_role' )"
            in effective_check
        )

    assert "acl.grantee <> defaults.defaclrole" in normalized_sql
    assert "unreviewed postgres role default-acl scope" in normalized_sql
    assert normalized_sql.count(reviewed_scope_clause) == expected_blocks
    assert (
        normalized_sql.count(
            "managed storage function default execute is not effective"
        )
        == expected_blocks
    )
    for broad_exclusion in (
        "namespace.nspname <> 'storage'",
        "namespace.nspname != 'storage'",
        "namespace.nspname is distinct from 'storage'",
    ):
        assert broad_exclusion not in normalized_sql


def assert_no_storage_ddl_or_dcl(sql: str) -> None:
    without_comments = re.sub(r"/\*.*?\*/|--[^\r\n]*", "", sql, flags=re.DOTALL)
    for statement in without_comments.split(";"):
        normalized_statement = normalized(statement)
        if re.match(
            r"^(?:alter|grant|revoke|create|drop|truncate)\b",
            normalized_statement,
        ):
            assert "in schema storage" not in normalized_statement
            assert not re.search(r"\bstorage\.", normalized_statement)


def assert_default_acl_diagnostics_do_not_filter_named_grantees(
    audit_sql: str,
    managed_diagnostic_sql: str,
) -> None:
    audit_section = normalized(numbered_section(audit_sql, 7, 8))
    assert " where " not in audit_section

    diagnostic = normalized(managed_diagnostic_sql)
    default_acl = diagnostic[
        diagnostic.index("with default_acl as (") : diagnostic.index(
            "), managed_role as ("
        )
    ]
    assert " where " not in default_acl
    for visible_role in ("public", "anon", "authenticated", "service_role"):
        assert visible_role in diagnostic


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
    assert_read_only_sql(VERIFY_PATH, expected_statements=14)
    assert_read_only_sql(HELPER_DIAGNOSTIC_PATH, expected_statements=1)
    assert_read_only_sql(MANAGED_DIAGNOSTIC_PATH, expected_statements=1)


def test_preflight_only_artifact_is_rollback_scoped_and_has_no_migration_ops() -> None:
    sql = read(PREFLIGHT_PATH)
    normalized_sql = normalized(sql)
    statements = parse_sql(sql)
    assert normalized_sql.startswith("/* phase 3.2b core preflight-only artifact.")
    assert normalized_sql.endswith("rollback;")
    assert preflight_do_block(sql) == preflight_do_block(read(MIGRATION_PATH))
    for safeguard in (
        "set local lock_timeout = '5s';",
        "set local statement_timeout = '5min';",
        "set local idle_in_transaction_session_timeout = '5min';",
        "set local search_path = pg_catalog;",
    ):
        assert normalized_sql.count(safeguard) == 1
    assert len(statements) == 7
    assert not re.search(
        r"(?im)^\s*(alter|create|drop|execute|grant|revoke|truncate|insert|update|delete)\b",
        sql,
    )


def test_only_explicit_migrations_contain_ddl_or_dcl_and_no_app_dml() -> None:
    mutation_paths = {MIGRATION_PATH, MANAGED_MIGRATION_PATH}
    for path in SQL_DIR.glob("*.sql"):
        if path == PREFLIGHT_PATH:
            continue
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


def test_audit_section_07_reports_every_namespace_scope() -> None:
    section = normalized(numbered_section(read(AUDIT_PATH), 7, 8))
    assert "pg_catalog.pg_default_acl" in section
    assert "coalesce(namespace.nspname, '<all_schemas>')" in section
    assert "schema_scope" in section
    assert "where namespace.nspname = 'public'" not in section
    assert "or defaults.defaclnamespace = 0" not in section
    assert "storage" in section


def test_default_acl_diagnostics_cannot_hide_additional_grantees() -> None:
    audit = read(AUDIT_PATH)
    diagnostic = read(MANAGED_DIAGNOSTIC_PATH)
    assert_default_acl_diagnostics_do_not_filter_named_grantees(audit, diagnostic)

    audit_mutant = audit.replace(
        "ORDER BY owner_name, schema_scope, object_type, grantee_name,",
        "WHERE grantee_role.rolname IN ('anon', 'authenticated')\n"
        "ORDER BY owner_name, schema_scope, object_type, grantee_name,",
        1,
    )
    assert audit_mutant != audit

    diagnostic_mutant = diagnostic.replace(
        "\n),\nmanaged_role AS (",
        "\n    WHERE grantee.rolname IN ('anon', 'authenticated')\n"
        "),\nmanaged_role AS (",
        1,
    )
    assert diagnostic_mutant != diagnostic
    with pytest.raises(AssertionError):
        assert_default_acl_diagnostics_do_not_filter_named_grantees(
            audit_mutant,
            diagnostic,
        )
    with pytest.raises(AssertionError):
        assert_default_acl_diagnostics_do_not_filter_named_grantees(
            audit,
            diagnostic_mutant,
        )


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


def test_product_enum_inventory_is_fail_closed_and_uses_live_type_name() -> None:
    forbidden_type = "product_" + "lifecycle_state"
    package_paths = (
        *SQL_DIR.glob("*.sql"),
        DOC_PATH,
        AUDIT_DOC_PATH,
        Path(__file__),
    )
    for path in package_paths:
        assert forbidden_type not in read(path), path

    preflight = normalized(preflight_do_block(read(MIGRATION_PATH)))
    for required_type in (
        "public.product_state",
        "public.custom_offering_state",
        "public.party_approval_state",
    ):
        assert f"pg_catalog.to_regtype('{required_type}') is null" in preflight
    assert "pg_catalog.format('public.product_%s_state', 'lifecycle')" in preflight
    assert ") is not null" in preflight

    for path in (MIGRATION_PATH, PREFLIGHT_PATH, VERIFY_PATH, DOC_PATH):
        assert "public.product_state" in read(path), path


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
    assert "actual_policy.check_expr is not null" in preflight
    assert "pg_catalog.pg_depend" in preflight
    assert "public.current_marketplace_party_id()'::regprocedure" in preflight
    assert "public.product'::regclass" in preflight
    assert "position('is_admin' in lower(actual_policy.using_expr)) > 0" in preflight
    assert "expected_canonical_expression" in preflight
    assert "canonical_policy_expression is distinct from" in preflight
    assert "or_operator_depth <= and_operator_depth" in preflight
    assert "policy artifacts already exist" in preflight
    assert "marketplace_party table privilege drift" in preflight
    assert "financial view select grant drift" in preflight
    assert "helper definition or security metadata drift" in preflight
    assert "managed storage default-acl signature drift" in preflight
    assert "unreviewed postgres role default-acl scope detected" in preflight
    assert "managed storage function default execute is not effective" in preflight
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


def test_mixed_policy_validator_rejects_role_only_alter() -> None:
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


@pytest.mark.parametrize(
    ("policy_name", "original", "replacement"),
    (
        (
            "custom_offering_select_published_or_own",
            "publication_state = 'published'::public.custom_offering_state",
            "publication_state <> 'published'::public.custom_offering_state",
        ),
        (
            "custom_offering_select_published_or_own",
            "marketplace_party_id = public.current_marketplace_party_id()",
            "marketplace_party_id = public.current_marketplace_party_id() or true",
        ),
        (
            "product_select_published_or_own",
            "lifecycle_state = 'published'::public.product_state",
            "lifecycle_state <> 'published'::public.product_state",
        ),
        (
            "product_select_published_or_own",
            "lifecycle_state = 'published'::public.product_state",
            "lifecycle_state != 'published'::public.product_state",
        ),
        (
            "product_select_published_or_own",
            "lifecycle_state = 'published'::public.product_state",
            "lifecycle_state is distinct from 'published'::public.product_state",
        ),
        (
            "product_select_published_or_own",
            "lifecycle_state = 'published'::public.product_state",
            "not ( lifecycle_state = 'published'::public.product_state )",
        ),
        (
            "product_select_published_or_own",
            "marketplace_party_id = public.current_marketplace_party_id()",
            "marketplace_party_id = public.current_marketplace_party_id() or true",
        ),
        (
            "product_select_published_or_own",
            "marketplace_party_id = public.current_marketplace_party_id()",
            "marketplace_party_id = public.current_marketplace_party_id() or ( 1 = 1 )",
        ),
        (
            "product_select_published_or_own",
            "marketplace_party_id = public.current_marketplace_party_id()",
            "marketplace_party_id = public.current_marketplace_party_id() or "
            "marketplace_party_id is null",
        ),
        (
            "product_select_published_or_own",
            "lifecycle_state = 'published'::public.product_state",
            "lifecycle_state = 'published'::public.product_state and "
            "marketplace_party_id is not null",
        ),
        (
            "product_color_select",
            "p.id = product_color.product_id",
            "p.category_id = product_color.product_id",
        ),
        (
            "product_color_select",
            "p.lifecycle_state = 'published'::public.product_state",
            "p.lifecycle_state <> 'published'::public.product_state",
        ),
        (
            "product_color_select",
            "p.marketplace_party_id = public.current_marketplace_party_id()",
            "p.marketplace_party_id <> public.current_marketplace_party_id()",
        ),
        (
            "product_color_select",
            "p.marketplace_party_id = public.current_marketplace_party_id()",
            "p.marketplace_party_id = public.is_admin()",
        ),
        (
            "product_color_select",
            "and ( p.lifecycle_state = 'published'::public.product_state or "
            "p.marketplace_party_id = public.current_marketplace_party_id() )",
            "and p.lifecycle_state = 'published'::public.product_state or "
            "p.marketplace_party_id = public.current_marketplace_party_id()",
        ),
    ),
    ids=(
        "custom-offering-reversed-publication-state",
        "custom-offering-or-true",
        "not-equal-angle",
        "not-equal-bang",
        "is-distinct-from",
        "not-negation",
        "or-true",
        "or-one-equals-one",
        "extra-or-branch",
        "extra-and-branch",
        "wrong-child-parent-join-column",
        "wrong-child-state-operator",
        "wrong-child-owner-operator",
        "wrong-helper-call",
        "wrong-child-grouping",
    ),
)
def test_mixed_policy_validator_rejects_semantic_mutations(
    policy_name: str,
    original: str,
    replacement: str,
) -> None:
    sql = normalized(read(MIGRATION_PATH))
    policy_alter = alter_policy_definition(sql, policy_name)
    mutated_alter = policy_alter.replace(original, replacement, 1)
    assert mutated_alter != policy_alter
    mutated = sql.replace(policy_alter, mutated_alter, 1)
    with pytest.raises(AssertionError):
        assert_complete_mixed_policy_alters(mutated)


def test_mixed_policy_checks_never_use_whitespace_only_expression_equality() -> None:
    for path in (MIGRATION_PATH, PREFLIGHT_PATH, VERIFY_PATH):
        assert_no_handcrafted_policy_expression_equality(read(path))

    restored = (
        read(MIGRATION_PATH)
        + """
    IF pg_catalog.regexp_replace(
        lower(pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true)),
        '[[:space:]]',
        '',
        'g'
    ) = pg_catalog.regexp_replace(
        lower(reviewed_expression),
        '[[:space:]]',
        '',
        'g'
    ) THEN
        NULL;
    END IF;
    """
    )
    with pytest.raises(AssertionError):
        assert_no_handcrafted_policy_expression_equality(restored)


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
    assert "expected_canonical_expression" in preflight
    assert "publication_state='published'::custom_offering_state" in preflight
    assert "expected_using_expression" not in preflight
    assert "lower(actual_policy.using_expr)" in preflight


def test_child_permissive_read_policies_never_add_admin_access() -> None:
    sql = normalized(read(MIGRATION_PATH))
    assert_no_child_admin_access(sql)

    owner_policy = policy_definition(sql, "phase32b_product_color_owner_read")
    owner_with_admin = owner_policy.replace(
        "parent_product.marketplace_party_id = public.current_marketplace_party_id()",
        "parent_product.marketplace_party_id = public.current_marketplace_party_id() "
        "or public.is_admin()",
        1,
    )
    assert owner_with_admin != owner_policy
    with pytest.raises(AssertionError):
        assert_no_child_admin_access(sql.replace(owner_policy, owner_with_admin, 1))

    mixed_policy = alter_policy_definition(sql, "product_color_select")
    mixed_with_admin = mixed_policy.replace(
        "p.marketplace_party_id = public.current_marketplace_party_id()",
        "p.marketplace_party_id = public.current_marketplace_party_id() "
        "or public.is_admin()",
        1,
    )
    assert mixed_with_admin != mixed_policy
    with pytest.raises(AssertionError):
        assert_no_child_admin_access(sql.replace(mixed_policy, mixed_with_admin, 1))


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


def test_core_default_changes_are_exactly_scoped_and_preserve_service_role() -> None:
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
    assert (
        "alter default privileges for role postgres grant execute on functions"
        " to service_role" in sql
    )
    assert not re.search(
        r"alter default privileges for role postgres\s+revoke all privileges"
        r" on (tables|sequences)",
        sql,
    )
    assert "managed storage default-acl signature drift" in sql
    assert "unreviewed postgres role default-acl scope" in sql
    assert "managed storage function default execute is not effective" in sql
    assert "client role must not inherit or assume service_role" in sql
    assert "explicit service_role future-function execute missing" in sql
    preflight = sql[: sql.index("-- existing public base-table grants")]
    assert "'f'::pg_catalog.\"char\", 'public'::name, 'anon'::name" in preflight
    assert "'f'::pg_catalog.\"char\", null::name" not in preflight


def test_core_preflight_and_postflight_require_exact_storage_signature() -> None:
    assert_storage_signature_guards(read(MIGRATION_PATH), expected_blocks=2)
    assert_storage_signature_guards(read(PREFLIGHT_PATH), expected_blocks=1)


def test_storage_signature_requires_managed_elevated_service_role() -> None:
    sql = read(MIGRATION_PATH)
    expected_start = sql.index("expected_storage_signature(")
    service_row = "('service_role'::name)"
    service_position = sql.index(service_row, expected_start)
    mutant = sql[:service_position] + sql[service_position + len(service_row) :]
    with pytest.raises(AssertionError):
        assert_storage_signature_guards(mutant, expected_blocks=2)


def test_service_role_is_never_classified_as_a_client_role() -> None:
    assert CLIENT_ROLES == {"anon", "authenticated"}
    assert MANAGED_ELEVATED_SERVER_ROLES == {"service_role"}
    assert CLIENT_ROLES.isdisjoint(MANAGED_ELEVATED_SERVER_ROLES)

    for path in (MIGRATION_PATH, PREFLIGHT_PATH, VERIFY_PATH):
        sql = normalized(read(path))
        assert "expected_storage_clients" not in sql
        assert "summary_storage_clients" not in sql
        assert "as client(role_oid)" not in sql

    verification = normalized(numbered_section(read(VERIFY_PATH), 13, 14))
    assert "anon/authenticated are client roles" in verification
    assert "service_role is a managed elevated server role" in verification
    assert "service_role is a client role" not in verification

    documentation = normalized(read(DOC_PATH))
    assert "`service_role` is a managed elevated server role" in documentation
    assert "`service_role` is not a client role" in documentation
    assert "`service_role` is a client role" not in documentation


def test_storage_signature_guard_rejects_broad_namespace_exclusion() -> None:
    sql = read(MIGRATION_PATH)
    mutant = sql.replace(
        "namespace.nspname IN ('public', 'storage')",
        "namespace.nspname <> 'storage'",
        1,
    )
    assert mutant != sql
    with pytest.raises(AssertionError):
        assert_storage_signature_guards(mutant, expected_blocks=2)


@pytest.mark.parametrize(
    ("original", "replacement"),
    (
        (
            "namespace.nspname IN ('public', 'storage')",
            "namespace.nspname IN ('public', 'storage', 'analytics')",
        ),
        (
            "defaults.defaclobjtype = 'f'::pg_catalog.\"char\"",
            "defaults.defaclobjtype IN ("
            "'f'::pg_catalog.\"char\", 'r'::pg_catalog.\"char\")",
        ),
        (
            "defaults.defaclobjtype = 'f'::pg_catalog.\"char\"",
            "defaults.defaclobjtype IN ("
            "'f'::pg_catalog.\"char\", 'S'::pg_catalog.\"char\")",
        ),
    ),
    ids=("other-namespace", "global-table", "global-sequence"),
)
def test_scope_guard_rejects_broadened_allowed_scopes(
    original: str,
    replacement: str,
) -> None:
    sql = read(MIGRATION_PATH)
    scope_start = sql.index("-- Only these postgres-owned role scopes")
    mutation_start = sql.index(original, scope_start)
    mutant = sql[:mutation_start] + replacement + sql[mutation_start + len(original) :]
    with pytest.raises(AssertionError):
        assert_storage_signature_guards(mutant, expected_blocks=2)


def test_storage_signature_guard_rejects_missing_or_extra_expected_privileges() -> None:
    sql = read(MIGRATION_PATH)
    missing = sql.replace(
        "('r'::pg_catalog.\"char\", 'TRIGGER'::text),",
        "",
        1,
    )
    assert missing != sql
    with pytest.raises(AssertionError):
        assert_storage_signature_guards(missing, expected_blocks=2)

    extra = sql.replace(
        "('r'::pg_catalog.\"char\", 'TRIGGER'::text),",
        "('r'::pg_catalog.\"char\", 'TRIGGER'::text),\n"
        "            ('r'::pg_catalog.\"char\", 'CREATE'::text),",
        1,
    )
    assert extra != sql
    with pytest.raises(AssertionError):
        assert_storage_signature_guards(extra, expected_blocks=2)


def test_storage_signature_guard_keeps_postgresql_17_maintain_gate() -> None:
    sql = read(MIGRATION_PATH)
    mutant = sql.replace(
        "current_setting('server_version_num')::integer >= 170000",
        "current_setting('server_version_num')::integer >= 150000",
        1,
    )
    assert mutant != sql
    with pytest.raises(AssertionError):
        assert_storage_signature_guards(mutant, expected_blocks=2)


@pytest.mark.parametrize(
    ("original", "replacement"),
    (
        (
            "owner_role.rolname AS owner_name",
            "'postgres'::name AS owner_name",
        ),
        (
            "namespace.nspname AS schema_name",
            "'storage'::name AS schema_name",
        ),
        (
            "defaults.defaclobjtype AS object_type",
            "'r'::pg_catalog.\"char\" AS object_type",
        ),
        (
            "CASE WHEN acl.grantee = 0 THEN 'PUBLIC'::name",
            "CASE WHEN acl.grantee = 0 THEN NULL::name",
        ),
        (
            "ELSE grantee_role.rolname",
            "ELSE 'anon'::name",
        ),
        (
            "acl.privilege_type,",
            "'SELECT'::text AS privilege_type,",
        ),
        (
            "acl.is_grantable",
            "false AS is_grantable",
        ),
        (
            "namespace.nspname = 'storage'",
            "namespace.nspname = 'public'",
        ),
        (
            "acl.grantee <> defaults.defaclrole",
            "acl.grantee IN (0, defaults.defaclrole)",
        ),
    ),
    ids=(
        "owner",
        "namespace",
        "object-type",
        "public-grantee-mapping",
        "named-grantee",
        "privilege",
        "grant-option",
        "storage-filter",
        "complete-non-owner-set",
    ),
)
def test_storage_signature_guard_reads_every_identity_dimension(
    original: str,
    replacement: str,
) -> None:
    sql = read(MIGRATION_PATH)
    actual_start = sql.index("actual_storage_signature AS")
    mutation_start = sql.index(original, actual_start)
    mutant = sql[:mutation_start] + replacement + sql[mutation_start + len(original) :]
    assert mutant != sql
    with pytest.raises(AssertionError):
        assert_storage_signature_guards(mutant, expected_blocks=2)


@pytest.mark.parametrize(
    ("removed", "added"),
    (
        (
            set(),
            {("postgres", "storage", "r", "PUBLIC", "SELECT", False)},
        ),
        (
            {("postgres", "storage", "r", "anon", "SELECT", False)},
            {("postgres", "storage", "r", "anon", "SELECT", True)},
        ),
        (
            {("postgres", "storage", "f", "service_role", "EXECUTE", False)},
            set(),
        ),
        (
            {("postgres", "storage", "S", "service_role", "USAGE", False)},
            {("postgres", "storage", "S", "service_role", "USAGE", True)},
        ),
        (
            set(),
            {("postgres", "storage", "f", "dashboard_user", "EXECUTE", False)},
        ),
        (
            set(),
            {("postgres", "storage", "r", "anon", "CREATE", False)},
        ),
        (
            {("postgres", "storage", "r", "anon", "TRIGGER", False)},
            set(),
        ),
        (
            {("postgres", "storage", "S", "authenticated", "USAGE", False)},
            {
                (
                    "supabase_admin",
                    "storage",
                    "S",
                    "authenticated",
                    "USAGE",
                    False,
                )
            },
        ),
        (
            set(),
            {("postgres", "storage", "T", "anon", "USAGE", False)},
        ),
    ),
    ids=(
        "public-grantee",
        "grant-option",
        "missing-service-role-row",
        "grantable-service-role-row",
        "unexpected-grantee",
        "extra-privilege",
        "missing-privilege",
        "wrong-owner",
        "unexpected-object-type",
    ),
)
def test_storage_signature_set_equality_rejects_every_metadata_mutation(
    removed: set[tuple[object, ...]],
    added: set[tuple[object, ...]],
) -> None:
    expected = expected_storage_signature(include_maintain=True)
    actual = (expected - removed) | added
    assert actual != expected
    assert (expected - actual) or (actual - expected)


def test_storage_signature_maintain_expectation_is_version_aware() -> None:
    pg17 = expected_storage_signature(include_maintain=True)
    pg15 = expected_storage_signature(include_maintain=False)
    assert len(pg17) == 36
    assert len(pg15) == 33
    for role_name in EXPECTED_STORAGE_ROLES:
        assert sum(row[3] == role_name for row in pg17) == 12
        assert sum(row[3] == role_name for row in pg15) == 11
    assert all(row[4] != "MAINTAIN" for row in pg15)
    assert {row for row in pg17 if row[4] == "MAINTAIN"} == {
        ("postgres", "storage", "r", "anon", "MAINTAIN", False),
        ("postgres", "storage", "r", "authenticated", "MAINTAIN", False),
        ("postgres", "storage", "r", "service_role", "MAINTAIN", False),
    }


@pytest.mark.parametrize(
    ("schema_name", "object_type"),
    (
        ("<all_schemas>", "r"),
        ("<all_schemas>", "S"),
        ("analytics", "r"),
        ("extensions", "f"),
    ),
    ids=("global-table", "global-sequence", "other-table", "other-function"),
)
def test_unreviewed_postgres_role_default_scopes_fail_closed(
    schema_name: str,
    object_type: str,
) -> None:
    assert not reviewed_postgres_role_default_scope(schema_name, object_type)


@pytest.mark.parametrize(
    ("schema_name", "object_type"),
    (
        ("public", "r"),
        ("public", "S"),
        ("public", "f"),
        ("storage", "r"),
        ("storage", "S"),
        ("storage", "f"),
        ("<all_schemas>", "f"),
    ),
)
def test_only_reviewed_postgres_role_default_scopes_are_admitted(
    schema_name: str,
    object_type: str,
) -> None:
    assert reviewed_postgres_role_default_scope(schema_name, object_type)


def test_core_and_optional_migrations_do_not_target_storage() -> None:
    for path in (MIGRATION_PATH, MANAGED_MIGRATION_PATH):
        assert_no_storage_ddl_or_dcl(read(path))

    for statement in (
        "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA storage FROM anon;",
        "REVOKE ALL PRIVILEGES ON TABLE storage.objects FROM service_role;",
        "GRANT SELECT ON TABLE storage.objects TO anon;",
        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA storage "
        "REVOKE EXECUTE ON FUNCTIONS FROM anon;",
    ):
        with pytest.raises(AssertionError):
            assert_no_storage_ddl_or_dcl(read(MIGRATION_PATH) + "\n" + statement)


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
    assert (
        "alter default privileges for role supabase_admin grant execute on functions"
        " to service_role" in optional
    )
    assert "client_roles_separate" in diagnostic
    assert "no_effective_client_default" in diagnostic
    assert "service_role_execute_expected" in diagnostic
    assert "service_role_execute_effective" in diagnostic
    assert "client role must not inherit or assume service_role" in optional
    assert "explicit service_role future-function execute missing" in optional
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


def test_sequence_default_acl_uses_distinct_catalog_and_acldefault_codes() -> None:
    effective_default_paths = (
        MIGRATION_PATH,
        VERIFY_PATH,
        MANAGED_DIAGNOSTIC_PATH,
        MANAGED_MIGRATION_PATH,
    )
    for path in SQL_DIR.glob("*.sql"):
        sql = read(path)
        assert not re.search(
            r"acldefault\s*\(\s*'S'::\s*pg_catalog\.\"char\"",
            sql,
        ), path

    for path in effective_default_paths:
        sql = read(path)
        assert "catalog_object_type" in sql, path
        assert "acldefault_object_type" in sql, path
        assert_sequence_acl_codes(sql)


def test_sequence_acl_code_validator_rejects_direct_and_indirect_uppercase() -> None:
    sql = read(VERIFY_PATH)
    assert_sequence_acl_codes(sql)

    indirect = sql.replace(
        "expected.acldefault_object_type_code",
        "expected.catalog_object_type_code",
        1,
    )
    assert indirect != sql
    with pytest.raises(AssertionError):
        assert_sequence_acl_codes(indirect)

    direct = sql.replace(
        "expected.acldefault_object_type_code",
        "'S'::pg_catalog.\"char\"",
        1,
    )
    assert direct != sql
    with pytest.raises(AssertionError):
        assert_sequence_acl_codes(direct)

    mapped_uppercase = sql.replace(
        "'s'::pg_catalog.\"char\"",
        "'S'::pg_catalog.\"char\"",
        1,
    )
    assert mapped_uppercase != sql
    with pytest.raises(AssertionError):
        assert_sequence_acl_codes(mapped_uppercase)


def test_core_has_fail_closed_transactional_postflight() -> None:
    sql = normalized(read(MIGRATION_PATH))
    start = sql.index("do $phase32b_postflight$")
    commit = sql.rindex("commit;")
    assert start < commit
    postflight = sql[start:commit]
    for invariant in (
        "34-table inventory or rls mismatch",
        "dangerous public, anon, or authenticated privilege remains",
        "anonymous select allowlist mismatch",
        "marketplace_party grant matrix mismatch",
        "seller insert policy mismatch",
        "financial view hardening mismatch",
        "mixed-policy mismatch",
        "expected read policy mismatch",
        "child write path mismatch",
        "helper mismatch",
        "anon helper dependency remains",
        "public_tables",
        "public_sequences",
        "public_functions",
        "global_functions",
        "managed storage default-acl signature drift",
        "unreviewed postgres role default-acl scope",
        "managed storage function default execute is not effective",
    ):
        assert invariant in postflight
    assert "raise exception" in postflight


def test_postflight_checks_authenticated_dangerous_privileges_on_every_table() -> None:
    sql = normalized(read(MIGRATION_PATH))
    assert_authenticated_dangerous_postflight(sql)
    clause = (
        "or exists ( select 1 from pg_catalog.pg_class as relation where "
        "relation.relnamespace = 'public'::regnamespace and relation.relkind "
        "in ('r', 'p') and pg_catalog.has_table_privilege( "
        "authenticated_role_oid, relation.oid, "
        "'truncate, references, trigger' ) ) then"
    )
    mutant = sql.replace(clause, "then", 1)
    assert mutant != sql
    with pytest.raises(AssertionError):
        assert_authenticated_dangerous_postflight(mutant)


def test_maintain_checks_are_dynamically_version_gated_for_postgresql_15() -> None:
    migration = normalized(read(MIGRATION_PATH))
    postflight = migration[migration.index("do $phase32b_postflight$") :]
    version_guard = "if current_setting('server_version_num')::integer >= 170000 then"
    assert version_guard in postflight
    maintain_check = postflight[postflight.index(version_guard) :]
    assert "execute $maintain_check$" in maintain_check
    assert "has_table_privilege($1, relation.oid, 'maintain')" in maintain_check
    assert "using anon_role_oid, authenticated_role_oid" in maintain_check
    assert not re.search(r"if .*>= 170000\s+and\s+exists", postflight)

    verification = normalized(read(VERIFY_PATH))
    assert not re.search(
        r"has_table_privilege\([^)]*'maintain'",
        verification,
    )
    assert "acl.privilege_type = 'maintain'" in verification


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
    assert "client_roles_separate" in section
    assert "pg_catalog.pg_has_role" in section
    assert "service_role_execute_expected" in section
    assert "service_role_execute_effective" in section
    assert "missing_explicit_service_role_function_execute_default" in section
    assert "missing_expected_postgres_default_acl" not in section


def test_verification_section_13_reports_exact_managed_storage_signature() -> None:
    section = numbered_section(read(VERIFY_PATH), 13, 14)
    normalized_section = normalized(section)
    assert "managed_storage_default_acl_signature" in normalized_section
    assert "reviewed_supabase_managed_storage_metadata" in normalized_section
    for field in (
        "expected_count",
        "actual_count",
        "missing_count",
        "unexpected_count",
        "failed_count",
        "check_passed",
        "finding_code",
    ):
        assert field in normalized_section
    assert "select * from expected_storage_signature" in normalized_section
    assert "select * from actual_storage_signature" in normalized_section
    assert normalized_section.count(" except ") >= 2
    assert "unexpected_non_public_defaults" in normalized_section
    assert "effective_function_missing" in normalized_section
    assert "expected_managed_storage_roles" in normalized_section
    assert "select service_role_oid from resolved_storage_roles" in normalized_section
    assert "as managed_role" in normalized_section
    assert "as client(role_oid)" not in normalized_section
    assert "('service_role'::name)" in section
    assert "privilege.privilege_type <> 'maintain'" in normalized_section
    assert "server_version_num')::integer >= 170000" in normalized_section
    expected_start = section.index("expected_storage_signature(")
    actual_start = section.index("actual_storage_signature AS", expected_start)
    expected_block = section[expected_start:actual_start]
    assert set(re.findall(r"\('([a-z_]+)'::name\)", expected_block)) == (
        EXPECTED_STORAGE_ROLES
    )
    assert (
        set(
            re.findall(
                r"\('([rSf])'::pg_catalog\.\"char\", '([A-Z]+)'::text\)",
                expected_block,
            )
        )
        == STORAGE_PRIVILEGES
    )


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
    assert "mixed_metadata" in section
    assert "expected_using_expression" not in section
    assert "pg_catalog.pg_depend" in section
    assert "pg_catalog.pg_policy" in section
    assert "expected_canonical_expression" in section
    assert "canonical_expression" in section
    assert "or_operator_depth > semantics.and_operator_depth" in section
    assert "lower(actual.qual) !~ 'is_admin'" in section


def test_verification_has_one_row_per_section_summary() -> None:
    section = normalized(read(VERIFY_PATH).split("-- 14.", maxsplit=1)[1])
    for field in (
        "section_number",
        "expected_count",
        "actual_count",
        "failed_count",
        "check_passed",
    ):
        assert field in section
    for section_number in range(1, 14):
        assert f"'{section_number:02d}'::text" in section
    assert "('05'::text, 30::bigint)" in section
    assert "('06'::text, 12::bigint)" in section
    assert "('11'::text, 4::bigint)" in section
    assert "('13'::text, 1::bigint)" in section
    assert "summary_managed_storage_roles" in section
    assert "select roles.service_role_oid" in section
    assert "('service_role'::name)" in section
    expected_start = section.index("summary_expected_storage_signature(")
    actual_start = section.index("summary_actual_storage_signature as", expected_start)
    expected_block = section[expected_start:actual_start]
    assert set(re.findall(r"\('([a-z_]+)'::name\)", expected_block)) == (
        EXPECTED_STORAGE_ROLES
    )
    assert "reviewed_supabase_managed_storage_metadata" in section
    assert "core_application_security" in section
    assert "separate_optional_not_evaluated_use_managed_role_diagnostic" in section


def test_documentation_corrects_admin_timeout_and_default_scope_claims() -> None:
    raw_doc = read(DOC_PATH)
    doc = normalized(raw_doc)
    assert "lock_timeout" in doc
    assert "rolls back" in doc
    assert "never" in doc and "increas" in doc
    assert "restrictive" in doc and "does not grant" in doc
    assert "supabase_admin" in doc
    assert "not fixed" in doc or "deferred" in doc
    assert "phase 3.2c" in doc
    assert raw_doc.count("## Verification") == 1
    assert "public.product_state" in raw_doc
    assert "preflight-only" in doc
    assert "managed_storage_default_acl_signature" in doc
    assert "all 14 verification sections" in doc
    assert "33 rows before postgresql 17" in doc
    assert "36 rows on postgresql 17 or newer" in doc


def test_audit_documentation_records_non_public_default_acl_blind_spot() -> None:
    doc = normalized(read(AUDIT_DOC_PATH))
    assert "section 07" in doc
    assert "every namespace scope" in doc
    assert "storage" in doc
    assert "blind spot" in doc
    assert "global" in doc
    assert "concealing `service_role`" in doc
    assert "bypasses rls" in doc
    assert "server-only" in doc


def test_security_artifacts_contain_no_secret_or_record_values() -> None:
    paths = (
        AUDIT_PATH,
        MIGRATION_PATH,
        PREFLIGHT_PATH,
        VERIFY_PATH,
        HELPER_DIAGNOSTIC_PATH,
        MANAGED_DIAGNOSTIC_PATH,
        MANAGED_MIGRATION_PATH,
        DOC_PATH,
        AUDIT_DOC_PATH,
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
