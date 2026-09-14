"""Static safety and coverage tests for the Phase 3.2C RLS audit package."""

import hashlib
import re
from pathlib import Path

from pglast import ast, parse_sql
from pglast.visitors import Visitor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = PROJECT_ROOT / "sql" / "phase-3.2c-rls-policy-audit.sql"
DOC_PATH = PROJECT_ROOT / "docs" / "phase-3.2c-rls-policy-audit.md"
PHASE_3_2B_DOC_PATH = PROJECT_ROOT / "docs" / "phase-3.2b-security-hardening.md"
LIVE_ACCEPTANCE_DOC_PATH = PROJECT_ROOT / "docs" / "phase-3.2b-live-rls-acceptance.md"
CORE_MIGRATION_PATH = PROJECT_ROOT / "sql" / "phase-3.2b-security-hardening.sql"
OPTIONAL_MIGRATION_PATH = (
    PROJECT_ROOT / "sql" / "phase-3.2b-supabase-admin-default-privileges-optional.sql"
)

README_DIGESTS = {
    "README": "537a1e494e2e1bcb472dfa12862e4dd0738cfadedfa06be8dc1e64eb73832093",
    "README.md": "2661b0908badf626e37a7e0f078060818a3a7ac765698212a151811692e9ecbf",
}
UNCHANGED_MIGRATION_DIGESTS = {
    CORE_MIGRATION_PATH: (
        "297eb2c853381e50bea9b1f009fe7e4714c68662f2c6168d14eb45081bf670d2"
    ),
    OPTIONAL_MIGRATION_PATH: (
        "df827163eeb7e333452086b7caecfb1b471eb727839450c6212f43b9a306f232"
    ),
}

EXPECTED_ROLES = {"PUBLIC", "anon", "authenticated", "service_role"}
EXPECTED_PRIVILEGES = {
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
    "MAINTAIN",
}
SENSITIVE_OBJECTS = {
    "purchase_order",
    "order_line_item",
    "payment",
    "commission",
    "refund",
    "commission_reversal",
    "settlement",
    "admin_user",
    "platform_config",
    "order_financial_position",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalized(source: str) -> str:
    return " ".join(source.lower().split())


def numbered_section(source: str, section: int) -> str:
    start = source.index(f"-- {section:02d}.")
    if section == 13:
        return source[start:]
    return source[start : source.index(f"-- {section + 1:02d}.", start)]


class NodeTypeCollector(Visitor):
    def __init__(self) -> None:
        self.node_types: set[type[ast.Node]] = set()

    def visit(self, _ancestors: object, node: ast.Node) -> None:
        self.node_types.add(type(node))


class RelationCollector(Visitor):
    def __init__(self) -> None:
        self.ctes: set[str] = set()
        self.relations: list[ast.RangeVar] = []

    def visit_CommonTableExpr(
        self,
        _ancestors: object,
        node: ast.CommonTableExpr,
    ) -> None:
        self.ctes.add(node.ctename)

    def visit_RangeVar(
        self,
        _ancestors: object,
        node: ast.RangeVar,
    ) -> None:
        self.relations.append(node)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_audit_parses_as_exactly_thirteen_select_only_statements() -> None:
    statements = parse_sql(read(AUDIT_PATH))

    assert len(statements) == 13
    assert all(isinstance(raw.stmt, ast.SelectStmt) for raw in statements)
    assert all(raw.stmt.intoClause is None for raw in statements)


def test_no_nested_mutation_ddl_dcl_procedure_or_copy_nodes_exist() -> None:
    statements = parse_sql(read(AUDIT_PATH))
    collector = NodeTypeCollector()
    collector(statements)

    prohibited = {
        ast.AlterTableStmt,
        ast.CallStmt,
        ast.CopyStmt,
        ast.CreateFunctionStmt,
        ast.CreatePolicyStmt,
        ast.CreateRoleStmt,
        ast.CreateStmt,
        ast.DeleteStmt,
        ast.DoStmt,
        ast.DropStmt,
        ast.GrantRoleStmt,
        ast.GrantStmt,
        ast.InsertStmt,
        ast.TruncateStmt,
        ast.UpdateStmt,
        ast.VariableSetStmt,
    }
    assert not collector.node_types & prohibited


def test_every_relation_source_is_a_catalog_or_cte_not_application_data() -> None:
    statements = parse_sql(read(AUDIT_PATH))
    collector = RelationCollector()
    collector(statements)

    assert collector.relations
    for relation in collector.relations:
        if relation.schemaname is not None:
            assert relation.schemaname == "pg_catalog"
        else:
            assert relation.relname in collector.ctes


def test_all_required_numbered_sections_exist_once() -> None:
    source = read(AUDIT_PATH)

    assert re.findall(r"(?m)^-- ([0-9]{2})\.", source) == [
        f"{section:02d}" for section in range(1, 14)
    ]


def test_policy_inventory_cannot_hide_roles_commands_or_expressions() -> None:
    section = normalized(numbered_section(read(AUDIT_PATH), 2))

    assert section.count(" where ") == 1
    assert "where policy.schemaname = 'public'" in section
    assert "policy.roles as policy_roles" in section
    assert "policy.cmd as policy_command" in section
    assert "policy.qual as complete_using_expression" in section
    assert "policy.with_check as complete_with_check_expression" in section
    assert "policy.cmd =" not in section
    assert "policy.policyname =" not in section
    assert "policy.roles &&" not in section


def test_for_all_count_is_dynamic_and_expands_to_exact_operations() -> None:
    source = read(AUDIT_PATH)
    inventory = normalized(numbered_section(source, 3))
    expansion = numbered_section(source, 4)

    assert "from pg_catalog.pg_policies" in inventory
    assert "policy.cmd = 'all'" in inventory
    assert "count(*)::bigint as current_for_all_policy_count" in inventory
    assert "no_current_for_all_policies" in inventory
    assert not re.search(r"(?:expected|current).*for_all.*(?:19|nineteen)", inventory)
    assert set(re.findall(r"\('([A-Z]+)'::text, [1-4]\)", expansion)) == {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
    }
    assert "COALESCE(" in expansion
    assert "raw_with_check_expression" in expansion
    assert "effective_with_check_expression" in expansion


def test_operation_review_emits_every_policy_and_required_risk_signals() -> None:
    section = normalized(numbered_section(read(AUDIT_PATH), 5))

    assert "select table_name, policy_name" in section
    assert "from review order by table_name" in section
    assert "where required_predicates_present" not in section
    for signal in (
        "required_predicates_present",
        "using_is_literal_true",
        "with_check_is_literal_true",
        "possible_tautology",
        "possible_owner_only_insert_check",
        "possible_state_transition_bypass",
        "policy_layer_approval_manipulation_risk",
        "possible_cross_principal_read",
        "possible_cross_principal_write",
        "unexpected_policy_role",
        "policy_assigned_to_public",
        "unexpected_admin_branch",
        "overlapping_permissive_policy_review_required",
    ):
        assert signal in section


def test_dependency_inventory_covers_required_catalog_objects_and_caveat() -> None:
    section = normalized(numbered_section(read(AUDIT_PATH), 6))

    for catalog in (
        "pg_catalog.pg_depend",
        "pg_catalog.pg_class",
        "pg_catalog.pg_proc",
        "pg_catalog.pg_type",
        "pg_catalog.pg_attribute",
    ):
        assert catalog in section
    assert "recursive_or_self_reference" in section
    assert "referenced_function_security_definer" in section
    assert "dependency presence does not prove" in section


def test_effective_matrix_has_all_roles_privileges_and_unfiltered_acl_entries() -> None:
    section = numbered_section(read(AUDIT_PATH), 7)

    assert EXPECTED_ROLES <= set(re.findall(r"'([A-Za-z_]+)'::name", section))
    assert EXPECTED_PRIVILEGES <= set(
        re.findall(r"\('([A-Z]+)'::text, [1-8]\)", section)
    )
    assert "pg_catalog.aclexplode" in section
    assert "acl.grantee = 0" in section
    assert "role_closure" in section
    table_acl_body = section[
        section.index("table_acl AS (") : section.index("policy_metadata AS (")
    ]
    assert "WHERE" not in table_acl_body
    assert "acl.grantee IN" not in table_acl_body


def test_maintain_and_sequence_acl_mapping_are_postgresql_15_safe() -> None:
    source = read(AUDIT_PATH)
    section = numbered_section(source, 7)

    assert "current_setting('server_version_num')::integer < 170000" in section
    assert not re.search(
        r"has_table_privilege\s*\([^)]*['\"]MAINTAIN['\"]",
        source,
        re.IGNORECASE | re.DOTALL,
    )
    assert "'S'::pg_catalog.\"char\"" in section
    assert "'s'::pg_catalog.\"char\"" in section
    assert "default_acl.defaclobjtype = object_type.catalog_object_type" in section
    assert "object_type.acldefault_object_type" in section
    assert not re.search(
        r"acldefault\s*\(\s*'S'::pg_catalog\.\"char\"",
        source,
    )
    assert "inherit_option" not in source
    assert "set_option" not in source


def test_role_membership_audits_all_paths_to_elevated_roles() -> None:
    section = numbered_section(read(AUDIT_PATH), 8)

    assert "WITH RECURSIVE" in section
    assert "pg_catalog.pg_auth_members" in section
    assert "rolinherit" in section
    assert "rolsuper" in section
    assert "rolbypassrls" in section
    assert "reached_managed_elevated_server_role" in section
    assert "unexpected_client_elevation_path" in section
    assert "reached.rolname = 'service_role'" in section


def test_force_rls_review_is_per_table_and_never_mechanical() -> None:
    sql = read(AUDIT_PATH)
    section = normalized(numbered_section(sql, 9))
    documentation = normalized(read(DOC_PATH))

    assert "from public_tables as table_metadata" in section
    assert "current_force_rls_enabled" in section
    assert "owner_bypass_materiality" in section
    assert "recorded_security_definer_functions" in section
    assert "service_or_background_job_requirements" in section
    assert "force_rls_candidate_classification" in section
    assert "requires_business_decision" in section
    assert "insufficient_evidence" in section
    assert "alter table" not in normalized(sql)
    assert "does not mechanically recommend enabling force rls" in documentation
    assert "no global force rls recommendation is made" in documentation


def test_financial_admin_and_parent_child_reviews_are_complete() -> None:
    source = read(AUDIT_PATH)
    focused = numbered_section(source, 10)
    relationships = normalized(numbered_section(source, 11))

    assert SENSITIVE_OBJECTS == set(
        re.findall(r"\([0-9]+, '([a-z0-9_]+)'::name,", focused)
    )
    assert "complete_policy_metadata" in focused
    assert "complete_view_definition" in focused
    assert "view_security_invoker_enabled" in focused
    assert "pg_catalog.pg_constraint" in relationships
    assert "constraint_metadata.contype = 'f'" in relationships
    assert "child_policy_references_parent_count" in relationships
    assert "parent_policy_references_child_count" in relationships
    assert "mutual_policy_dependency_review_required" in relationships
    assert "recursive_policy_review_required" in relationships


def test_prioritized_findings_and_empty_result_reporting_have_required_shape() -> None:
    section = normalized(numbered_section(read(AUDIT_PATH), 12))

    for column in (
        "finding_id",
        "severity",
        "table",
        "policy",
        "finding",
        "evidence",
        "recommended_decision",
        "migration_required",
        "human_business_decision_required",
    ):
        assert column in section
    assert "proven_structural_finding" in section
    assert "business_semantics_hypothesis" in section
    assert "phase32c_none" in section
    assert "empty_result_confirmed" in section
    assert "where not exists (select 1 from numbered_findings)" in section


def test_final_summary_reports_expected_actual_failed_and_status() -> None:
    section = normalized(numbered_section(read(AUDIT_PATH), 13))

    assert set(re.findall(r"'([0-9]{2}_[a-z0-9_]+)'", section)) == {
        f"{number:02d}_{name}"
        for number, name in (
            (1, "public_base_table_inventory"),
            (2, "complete_policy_inventory"),
            (3, "dynamic_for_all_inventory"),
            (4, "for_all_operation_expansion"),
            (5, "operation_predicate_review"),
            (6, "policy_dependency_inventory"),
            (7, "effective_policy_grant_matrix"),
            (8, "role_membership_inheritance"),
            (9, "force_rls_suitability"),
            (10, "financial_administrative_review"),
            (11, "parent_child_recursion_review"),
            (12, "prioritized_findings"),
        )
    }
    assert "expected_checks" in section
    assert "actual_checks" in section
    assert "failed_checks" in section
    assert "end as status" in section


def test_documentation_contains_run_return_semantics_and_no_remediation() -> None:
    documentation = normalized(read(DOC_PATH))

    for requirement in (
        "run one numbered statement at a time",
        "result-return template",
        "proven findings versus hypotheses",
        "`for all` semantics",
        "force rls tradeoffs",
        "no phase 3.2c remediation migration exists",
        "phase 3.2b core migration",
        "optional `supabase_admin` package",
        "was not run against supabase",
    ):
        assert requirement in documentation


def test_phase_3_2b_evidence_is_safe_and_migrations_are_byte_unchanged() -> None:
    hardening_doc = read(PHASE_3_2B_DOC_PATH)
    acceptance_doc = read(LIVE_ACCEPTANCE_DOC_PATH)
    combined_docs = hardening_doc + acceptance_doc

    assert "all 13 substantive verification sections" in hardening_doc
    assert "staged RLS acceptance checks passed" in hardening_doc
    assert "passed on the reviewed fake-data testing branch" in acceptance_doc
    assert "@furnihub.test" not in combined_docs
    for path, expected_digest in UNCHANGED_MIGRATION_DIGESTS.items():
        assert sha256(path) == expected_digest


def test_readme_files_are_byte_unchanged() -> None:
    for filename, expected_digest in README_DIGESTS.items():
        assert sha256(PROJECT_ROOT / filename) == expected_digest
