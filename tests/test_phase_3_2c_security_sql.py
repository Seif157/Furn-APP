"""Static, fail-closed tests for the review-only Phase 3.2C package."""

import hashlib
import re
from pathlib import Path

from pglast import ast, parse_sql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = PROJECT_ROOT / "sql"
CORE_PATH = SQL_DIR / "phase-3.2c-security-hardening.sql"
PREFLIGHT_PATH = SQL_DIR / "phase-3.2c-security-hardening-preflight.sql"
VERIFY_PATH = SQL_DIR / "phase-3.2c-security-hardening-verify.sql"
DOC_PATH = PROJECT_ROOT / "docs" / "phase-3.2c-security-hardening.md"

PRESERVED_DIGESTS = {
    PROJECT_ROOT / "README": (
        "537a1e494e2e1bcb472dfa12862e4dd0738cfadedfa06be8dc1e64eb73832093"
    ),
    PROJECT_ROOT / "README.md": (
        "2661b0908badf626e37a7e0f078060818a3a7ac765698212a151811692e9ecbf"
    ),
    SQL_DIR / "phase-3.2b-security-hardening.sql": (
        "297eb2c853381e50bea9b1f009fe7e4714c68662f2c6168d14eb45081bf670d2"
    ),
    SQL_DIR / "phase-3.2b-supabase-admin-default-privileges-optional.sql": (
        "df827163eeb7e333452086b7caecfb1b471eb727839450c6212f43b9a306f232"
    ),
}

EXPECTED_PUBLIC_TABLES = {
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

ALLOWED_DISPOSITIONS = {
    "remediated",
    "accepted with evidence",
    "audit false positive",
    "deferred pending a named business decision",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalized(path: Path) -> str:
    return re.sub(r"\s+", " ", read(path).lower()).strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight_block(sql: str) -> str:
    start = sql.index("DO $phase32c_preflight$")
    marker = "$phase32c_preflight$;"
    end = sql.index(marker, start) + len(marker)
    return sql[start:end]


def test_every_phase32c_sql_artifact_parses() -> None:
    for path in (CORE_PATH, PREFLIGHT_PATH, VERIFY_PATH):
        assert parse_sql(read(path))


def test_preserved_readmes_and_phase32b_migrations_are_byte_identical() -> None:
    for path, expected_digest in PRESERVED_DIGESTS.items():
        assert sha256(path) == expected_digest


def test_core_is_one_transaction_with_local_safeguards_and_postflight() -> None:
    sql = normalized(CORE_PATH)
    assert sql.count(" begin;") + sql.startswith("begin;") == 1
    assert sql.count(" commit;") == 1
    assert sql.endswith("commit;")
    preflight = sql.index("do $phase32c_preflight$")
    first_change = sql.index("create or replace function")
    postflight = sql.index("do $phase32c_postflight$")
    commit = sql.rindex("commit;")
    assert preflight < first_change < postflight < commit
    for setting in (
        "set local lock_timeout",
        "set local statement_timeout",
        "set local idle_in_transaction_session_timeout",
        "set local search_path = pg_catalog",
    ):
        assert sql.index(setting) < preflight


def test_standalone_preflight_rolls_back_and_cannot_drift() -> None:
    core = read(CORE_PATH)
    standalone = read(PREFLIGHT_PATH)
    assert preflight_block(core) == preflight_block(standalone)
    for safeguard in (
        "SET LOCAL lock_timeout = '5s';",
        "SET LOCAL statement_timeout = '5min';",
        "SET LOCAL idle_in_transaction_session_timeout = '5min';",
        "SET LOCAL search_path = pg_catalog;",
    ):
        assert safeguard in core
        assert safeguard in standalone
    parsed = parse_sql(standalone)
    assert standalone.count("BEGIN;") == 1
    assert standalone.count("ROLLBACK;") == 1
    assert "COMMIT;" not in standalone
    assert isinstance(parsed[-1].stmt, ast.TransactionStmt)
    lower = standalone.replace(preflight_block(standalone), "").lower()
    for persistent in (
        "create policy",
        "drop policy",
        "create view",
        "create or replace function",
        "alter function",
        "alter view",
        "grant ",
        "revoke ",
    ):
        assert persistent not in lower


def test_preflight_exact_inventory_rls_roles_and_pseudo_public_handling() -> None:
    block = preflight_block(read(CORE_PATH))
    lower = block.lower()
    expected_array = block[block.index("expected_tables constant text[]") :]
    names = set(re.findall(r"^\s*'([a-z0-9_]+)'[,]?$", expected_array, re.MULTILINE))
    assert EXPECTED_PUBLIC_TABLES <= names
    assert len(EXPECTED_PUBLIC_TABLES) == 34
    assert "select table_name from expected\n        except" in lower
    assert "select table_name from actual\n        except" in lower
    assert "not relation.relrowsecurity" in lower
    assert "relation.relforcerowsecurity" in lower
    assert "acl.grantee = 0" in lower
    assert "to_regrole('public')" not in lower
    assert "pg_has_role" in lower
    assert "rolbypassrls" in lower
    assert "rolsuper" in lower


def test_preflight_is_exact_and_fail_closed_on_unresolved_evidence() -> None:
    block = normalized(CORE_PATH)
    assert "phase 3.2c review column inventory drift" in block
    assert "phase 3.2c review target-kind enum drift" in block
    assert "phase 3.2c furnishing lifecycle enum drift" in block
    assert "phase 3.2c policy/view baseline drift" in block
    assert "phase 3.2c financial view baseline drift" in block
    assert "phase 3.2c for all policy count drift" in block
    assert "reviewed_19_policies_and_122_findings" in block
    assert "customer_direct_withdrawal_not_approved" in block
    assert "customer_insert_draft_only_approved" in block
    assert "disposition evidence gate is unresolved" in block
    assert "withdrawal workflow decision is unresolved" in block
    assert "initial-state decision is unresolved" in block
    assert "pg_catalog.pg_depend" in block
    assert "furnishing_request_write_own" in block


def test_helper_uses_empty_path_qualified_body_and_exact_grants() -> None:
    sql = normalized(CORE_PATH)
    assert (
        "create or replace function public.current_customer_profile_id() "
        "returns pg_catalog.uuid language sql stable security definer "
        "set search_path = ''" in sql
    )
    assert "from public.customer_profile as customer" in sql
    assert "where customer.user_id = auth.uid()" in sql
    assert (
        "alter function public.current_customer_profile_id() owner to postgres" in sql
    )
    assert "from public, anon, authenticated, service_role" in sql
    assert "to authenticated, service_role" in sql
    helper_part = sql[
        sql.index("create or replace function") : sql.index("-- raw review")
    ]
    assert "grant execute" in helper_part
    assert "to anon" not in helper_part
    assert "to public" not in helper_part


def test_review_projection_is_fixed_read_only_and_eligibility_scoped() -> None:
    sql = normalized(CORE_PATH)
    view = sql[
        sql.index("create view public.public_review") : sql.index(
            "-- restrictive guards"
        )
    ]
    assert "revoke select on table public.review from public, anon" in sql
    assert "with (security_barrier = true, security_invoker = false)" in view
    assert view.count("review_row.id") == 2
    projection = (
        "select review_row.id, review_row.target_kind, "
        "review_row.target_product_id, review_row.target_marketplace_party_id, "
        "review_row.rating, review_row.comment, review_row.created_at"
    )
    assert view.count(projection) == 2
    assert "review_row.customer_profile_id" not in view
    assert "select review_row.target_service_request_id" not in view
    assert view.count("target_service_request_id is null") == 2
    assert "target_kind::text = 'service_request'" not in view
    assert "union all" in view
    assert "lifecycle_state = 'published'::public.product_state" in view
    assert view.count("approval_state = 'approved'::public.party_approval_state") == 2
    assert "product_category.is_active" in view
    assert "available_color.stock_quantity > 0" in view
    assert "revoke all privileges on table public.public_review" in view
    assert (
        "grant select on table public.public_review to anon, authenticated, "
        "service_role" in view
    )


def test_raw_review_authenticated_guard_is_restrictive_owner_or_admin() -> None:
    sql = normalized(CORE_PATH)
    policy = sql[
        sql.index("create policy phase32c_review_authenticated_read_guard") : sql.index(
            "create view public.public_review"
        )
    ]
    assert "as restrictive for select to authenticated" in policy
    assert "customer_profile_id = public.current_customer_profile_id()" in policy
    assert "or public.is_admin()" in policy
    assert "to anon" not in policy


def test_service_directory_guards_cannot_be_literal_true() -> None:
    sql = normalized(CORE_PATH)
    service = sql[
        sql.index("create policy phase32c_service_type_anon_read_guard") : sql.index(
            "-- the review gate"
        )
    ]
    assert service.count("as restrictive for select") == 4
    assert "phase32c_service_type_anon_read_guard" in service
    assert "using (is_active)" in service
    assert "phase32c_service_type_authenticated_read_guard" in service
    assert "is_active or public.is_admin()" in service
    assert "phase32c_party_capability_anon_read_guard" in service
    assert (
        "capability_party.approval_state = 'approved'::public.party_approval_state"
        in service
    )
    assert "capability_service.is_active" in service
    assert "marketplace_party_id = public.current_marketplace_party_id()" in service
    assert "or public.is_admin()" in service
    assert "using (true)" not in service


def test_furnishing_for_all_is_split_without_select_or_unapproved_states() -> None:
    sql = normalized(CORE_PATH)
    furnishing = sql[
        sql.index("drop policy furnishing_request_write_own") : sql.index(
            "-- preserve the invoker-rights"
        )
    ]
    assert "for all" not in furnishing
    assert furnishing.count("create policy") == 3
    assert furnishing.count("for insert") == 1
    assert furnishing.count("for update") == 1
    assert furnishing.count("for delete") == 1
    assert "for select" not in furnishing
    assert "and lifecycle_state::text = 'draft'" in furnishing
    assert furnishing.count("lifecycle_state::text in ('draft', 'open')") == 3
    assert (
        furnishing.count("customer_profile_id = public.current_customer_profile_id()")
        == 4
    )
    for locked_state in ("accepted", "withdrawn", "closed"):
        assert f"'{locked_state}'" not in furnishing


def test_financial_view_definition_and_service_access_are_preserved() -> None:
    sql = normalized(CORE_PATH)
    finance = sql[
        sql.index(
            "revoke all privileges on table public.order_financial_position"
        ) : sql.index("do $phase32c_postflight$")
    ]
    assert "create view public.order_financial_position" not in sql
    assert "alter view public.order_financial_position" not in sql
    assert "from public, anon, authenticated" in finance
    assert "to authenticated" in finance
    assert "service_role" not in finance
    assert "security_invoker=true" in sql


def test_core_has_no_storage_default_acl_force_rls_rows_or_dynamic_sql() -> None:
    sql = normalized(CORE_PATH)
    assert "storage." not in sql
    assert "pg_default_acl" not in sql
    assert "alter default privileges" not in sql
    assert "force row level security" not in sql
    assert "enable row level security" not in sql
    assert "regexp_replace" not in sql
    assert not re.search(r"\bexecute\s+(?:format|\$|')", sql)
    assert not re.search(
        r"(?:^|;)\s*(?:insert\s+into|update\s+public\.|delete\s+from)", sql
    )


def test_postflight_precedes_commit_and_checks_all_target_security_results() -> None:
    sql = normalized(CORE_PATH)
    postflight = sql[sql.index("do $phase32c_postflight$") : sql.rindex("commit;")]
    for marker in (
        "postflight helper hardening mismatch",
        "postflight review exposure mismatch",
        "postflight public-review write exposure",
        "postflight policy inventory mismatch",
        "postflight changed rls/force state",
        "postflight financial-view privilege mismatch",
        "postflight service-role functionality mismatch",
    ):
        assert marker in postflight


def test_verifier_is_exactly_sixteen_select_only_sections_with_uniform_shape() -> None:
    verify = read(VERIFY_PATH)
    statements = parse_sql(verify)
    assert len(statements) == 16
    assert all(isinstance(statement.stmt, ast.SelectStmt) for statement in statements)
    assert len(re.findall(r"(?m)^-- (?:0[1-9]|1[0-6])\.", verify)) == 16
    for raw_statement in re.split(r";\s*(?=(?:\n|$))", verify):
        if "check_name" not in raw_statement:
            continue
        lowered = raw_statement.lower()
        for field in (
            "expected_count",
            "actual_count",
            "failed_count",
            "check_passed",
        ):
            assert field in lowered


def test_verifier_covers_all_required_security_outcomes() -> None:
    verify = normalized(VERIFY_PATH)
    for marker in (
        "customer_profile_helper",
        "raw_review_anon_denial",
        "safe_public_review_projection",
        "public_service_request_review_denial",
        "active_service_type_public_read",
        "safe_public_party_capability",
        "service_directory_owner_admin_paths",
        "furnishing_request_operation_policies",
        "furnishing_request_locked_states",
        "financial_view_authenticated_select_only",
        "phase32b_catalogue_policies_unchanged",
        "service_role_functional",
        "client_role_separation",
        "unexpected_public_privileges",
        "managed_storage_default_acl_unchanged",
        "verification_section_inventory",
    ):
        assert marker in verify
    assert "30::bigint" in verify


def test_storage_verification_uses_exact_three_role_version_aware_signature() -> None:
    verify = read(VERIFY_PATH)
    section = verify[verify.index("-- 15.") : verify.index("-- 16.")]
    assert section.count("('anon'::name)") == 1
    assert section.count("('authenticated'::name)") == 1
    assert section.count("('service_role'::name)") == 1
    assert "('S'::pg_catalog.\"char\", 's'::pg_catalog.\"char\"" in section
    assert "pg_catalog.acldefault(" in section
    assert "object_type.acldefault_object_type" in section
    assert "current_setting('server_version_num')::integer >= 170000" in section
    assert "expected_signature" in section
    assert "actual_signature" in section
    assert section.count("EXCEPT") == 2
    assert "owner_role.rolname = 'postgres'" in section
    assert "namespace.nspname = 'storage'" in section
    assert "acl.is_grantable" in section


def test_document_has_exact_disposition_counts_and_allowed_classifications() -> None:
    doc = read(DOC_PATH)
    classification_pattern = (
        "remediated|accepted with evidence|audit false positive|"
        "deferred pending a named business decision"
    )
    for_all_rows = re.findall(
        rf"^\| for_all_(\d{{2}}) \|.*?\| ({classification_pattern}) \|",
        doc,
        re.MULTILINE,
    )
    finding_rows = re.findall(
        rf"^\| phase32c_(\d{{4}}) \| ({classification_pattern}) \|",
        doc,
        re.MULTILINE,
    )
    assert [number for number, _ in for_all_rows] == [f"{i:02d}" for i in range(1, 20)]
    assert [number for number, _ in finding_rows] == [f"{i:04d}" for i in range(1, 123)]
    assert all(
        classification in ALLOWED_DISPOSITIONS for _, classification in for_all_rows
    )
    assert all(
        classification in ALLOWED_DISPOSITIONS for _, classification in finding_rows
    )
    assert "122 vulnerabilities existed" in doc
    assert "audit false positive for a policy-only signal" in doc
    assert "Human security review required; not approved for deployment." in doc


def test_document_records_api_and_withdrawal_blockers_without_duplicate_heading() -> (
    None
):
    doc = read(DOC_PATH)
    lower = doc.lower()
    assert "anonymous review reads must move" in lower
    assert "no repository application code or tests establish" in lower
    assert "fixture_precondition_not_met" in doc
    assert doc.count("## Verification") == 1


def test_review_security_mutations_would_break_static_contract() -> None:
    sql = normalized(CORE_PATH)

    def satisfies_contract(candidate: str) -> bool:
        return all(
            (
                "revoke select on table public.review from public, anon" in candidate,
                candidate.count("target_service_request_id is null") == 2,
                "using (is_active)" in candidate,
                candidate.count("lifecycle_state::text in ('draft', 'open')") == 3,
            )
        )

    mutations = (
        sql.replace(
            "revoke select on table public.review from public, anon",
            "revoke select on table public.review from public",
            1,
        ),
        sql.replace("target_service_request_id is null", "true", 1),
        sql.replace("using (is_active)", "using (true)", 1),
        sql.replace("lifecycle_state::text in ('draft', 'open')", "true", 1),
    )
    assert satisfies_contract(sql)
    assert not any(satisfies_contract(candidate) for candidate in mutations)
