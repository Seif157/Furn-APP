"""Static tests binding the Phase 3.2D scoping packs to the audit evidence."""

import csv
import re
from collections import Counter
from pathlib import Path

from pglast import ast, parse_sql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS = PROJECT_ROOT / "docs"
LEDGER_PATH = DOCS / "phase-3.2c-security-hardening.md"
SCOPING_PATH = DOCS / "phase-3.2d-scoping.md"
SECTION03_PATH = DOCS / "evidence" / "phase-3.2c" / "section-03-for-all.csv"
SECTION02_PATH = DOCS / "evidence" / "phase-3.2d" / "section-02-policies.csv"
SECTION05_PATH = DOCS / "evidence" / "phase-3.2d" / "section-05-operation-review.csv"
DIAGNOSTIC_PATH = PROJECT_ROOT / "sql" / "phase-3.2d-column-inventory-diagnostic.sql"
DEFERRED = "deferred_with_named_blocker"
STATUS = "Human security review required; not approved for deployment."

SECTION02_HEADERS = (
    "schema_name",
    "table_name",
    "policy_name",
    "policy_mode",
    "policy_roles",
    "policy_command",
    "complete_using_expression",
    "complete_with_check_expression",
)
SECTION05_HEADERS = (
    "table_name",
    "policy_name",
    "policy_mode",
    "policy_roles",
    "operation_name",
    "effective_using_expression",
    "effective_with_check_expression",
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
    "overlapping_permissive_policy_count",
    "overlapping_permissive_policy_review_required",
)
BOOLEAN_FLAGS = SECTION05_HEADERS[7:19] + SECTION05_HEADERS[20:]
SIGNAL_FLAGS = tuple(
    flag for flag in BOOLEAN_FLAGS if flag != "required_predicates_present"
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def squash(expression: str) -> str:
    return " ".join(expression.split())


def tokens(expression: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_.:']+", expression)


def csv_rows(path: Path, headers: tuple[str, ...]) -> list[dict[str, str]]:
    assert path.is_file(), f"missing evidence: {path}"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == headers
        rows = list(reader)
    assert all(None not in row for row in rows)
    return rows


def section02() -> dict[tuple[str, str], dict[str, str]]:
    rows = csv_rows(SECTION02_PATH, SECTION02_HEADERS)
    identities = [(row["table_name"], row["policy_name"]) for row in rows]
    assert len(identities) == len(set(identities))
    assert all(row["schema_name"] == "public" for row in rows)
    return dict(zip(identities, rows, strict=True))


def section05() -> list[dict[str, str]]:
    rows = csv_rows(SECTION05_PATH, SECTION05_HEADERS)
    for row in rows:
        assert all(row[flag] in {"true", "false"} for flag in BOOLEAN_FLAGS)
        assert row["overlapping_permissive_policy_count"].isdigit()
        assert row["operation_name"] in {"SELECT", "INSERT", "UPDATE", "DELETE"}
    return rows


def deferred_policies() -> set[tuple[str, str]]:
    pattern = re.compile(
        r"^\| ([a-z0-9_]+) \| ([a-z0-9_]+) \| (?:PERMISSIVE|RESTRICTIVE) \| "
        r"\{[a-z_,]+\} \| ([a-z_]+) \| [^|]+ \|$",
        re.MULTILINE,
    )
    rows = pattern.findall(read(LEDGER_PATH))
    assert len(rows) == 19
    return {(table, policy) for table, policy, cls in rows if cls == DEFERRED}


def deferred_findings() -> dict[str, tuple[str, str, str]]:
    pattern = re.compile(
        r"^\| (phase32c_\d{4}) \| ([a-z]+) \| ([a-z0-9_]+) \| ([^|]+) \| "
        r"[a-z0-9_]+ \| ([a-z_]+) \| ([^|]+) \|$",
        re.MULTILINE,
    )
    rows = pattern.findall(read(LEDGER_PATH))
    assert len(rows) == 122
    return {
        finding_id: (severity, table, policy.strip())
        for finding_id, severity, table, policy, cls, _basis in rows
        if cls == DEFERRED
    }


def pack(doc: str, start: str, end: str) -> str:
    return doc[doc.index(start) : doc.index(end)]


def test_scoping_document_is_planning_only() -> None:
    doc = read(SCOPING_PATH)
    assert doc.startswith("# Phase 3.2D scoping")
    assert "Status: **Planning only; no SQL, no migration, no live access.**" in doc
    assert doc.count(STATUS) == 2
    assert set((PROJECT_ROOT / "sql").glob("phase-3.2d*")) == {
        DIAGNOSTIC_PATH,
        PROJECT_ROOT / "sql" / "phase-3.2d-security-hardening.sql",
        PROJECT_ROOT / "sql" / "phase-3.2d-security-hardening-preflight.sql",
        PROJECT_ROOT / "sql" / "phase-3.2d-security-hardening-verify.sql",
    }
    assert not list((PROJECT_ROOT / "scripts").glob("*3_2d*"))


def test_column_inventory_diagnostic_is_four_select_only_catalog_statements() -> None:
    sql = read(DIAGNOSTIC_PATH)
    statements = parse_sql(sql)
    assert len(statements) == 4
    assert all(isinstance(raw.stmt, ast.SelectStmt) for raw in statements)
    assert len(re.findall(r"(?m)^-- 0[1-4]\.", sql)) == 4
    # Strip comments and string literals so only executable SQL is scanned.
    stripped = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    stripped = re.sub(r"--[^\n]*", " ", stripped)
    stripped = re.sub(r"'[^']*'", "''", stripped)
    lowered = stripped.lower()
    for forbidden in (
        "begin",
        "commit",
        "rollback",
        "do $",
        "insert into",
        "update ",
        "delete from",
        "create ",
        "alter ",
        "drop ",
        "grant ",
        "revoke ",
        "execute ",
        "set ",
    ):
        assert forbidden not in lowered, forbidden
    lowered = sql.lower()
    assert "pg_catalog" in lowered
    for table in (
        "customer_profile",
        "design",
        "design_version",
        "design_product_reference",
        "party_capability",
        "service_request",
        "purchase_order",
        "order_line_item",
        "review",
    ):
        assert lowered.count(f"'{table}'") >= 3, table
    assert "attidentity" in lowered
    assert "attgenerated" in lowered
    assert "has_column_privilege" in lowered
    assert "pg_enum" in lowered
    assert "pg_get_constraintdef" in lowered


def test_section02_export_matches_documented_counts_and_pre_migration_state() -> None:
    policies = section02()
    assert len(policies) == 114
    assert len({table for table, _policy in policies}) == 34
    commands = Counter(row["policy_command"] for row in policies.values())
    assert commands["ALL"] == 19
    modes = Counter(row["policy_mode"] for row in policies.values())
    assert modes == {"PERMISSIVE": 89, "RESTRICTIVE": 25}
    assert not any(policy.startswith("phase32c_") for _table, policy in policies)
    assert ("furnishing_request", "furnishing_request_write_own") in policies
    assert all(
        policy.startswith("phase32b_")
        for (_table, policy), row in policies.items()
        if row["policy_mode"] == "RESTRICTIVE"
    )
    admin = [
        row for (_table, policy), row in policies.items() if policy.endswith("_admin")
    ]
    assert len(admin) == 21
    assert all(
        squash(row["complete_using_expression"]) == "is_admin()" for row in admin
    )

    with SECTION03_PATH.open(encoding="utf-8", newline="") as handle:
        section03 = {
            (row["table_name"], row["policy_name"]): row
            for row in csv.DictReader(handle)
            if row["result_kind"] == "policy"
        }
    for_all = {
        identity for identity, row in policies.items() if row["policy_command"] == "ALL"
    }
    assert for_all == set(section03)
    for identity in for_all:
        assert squash(policies[identity]["complete_using_expression"]) == squash(
            section03[identity]["complete_using_expression"]
        )


def test_section05_export_covers_every_policy_and_documented_counts() -> None:
    rows = section05()
    policies = section02()
    assert len(rows) == 171
    assert {(row["table_name"], row["policy_name"]) for row in rows} == set(policies)
    flagged = sum(
        row["overlapping_permissive_policy_review_required"] == "true" for row in rows
    )
    assert flagged == 69
    doc = read(SCOPING_PATH)
    assert "| 171 rows over the same 114 policies |" in doc
    assert "114 policies, 34 tables, 19 `FOR ALL`, 89 permissive, 25 restrictive" in doc


def test_pack_a_reconciles_exactly_with_deferred_for_all_policies() -> None:
    doc = read(SCOPING_PATH)
    section = pack(doc, "## Pack A", "## Pack B")
    rows = re.findall(r"^\| ([a-z0-9_]+) \| ([a-z0-9_]+) \| `[^`]+` \|$", section, re.M)
    assert len(rows) == len(set(rows))
    assert set(rows) == deferred_policies()
    assert len(rows) == 10
    assert "| 2 | A — `FOR ALL` operation scope | 10 policies |" in doc


def test_packs_b_c_d_partition_deferred_findings_exactly() -> None:
    doc = read(SCOPING_PATH)
    expected = deferred_findings()
    assert len(expected) == 46

    pack_c = re.findall(
        r"^\| (phase32c_\d{4}) \| ([a-z0-9_]+) \| ([a-z0-9_]+) \| [a-z_]+ \|$",
        pack(doc, "## Pack C", "### Complete predicates"),
        re.M,
    )
    pack_b = re.findall(
        r"^\| (phase32c_\d{4}) \| ([a-z0-9_]+) \| ([a-z0-9_]+) \| [^|]+ \| [^|]+ \|$",
        pack(doc, "## Pack B", "## Pack D"),
        re.M,
    )
    pack_d_rows = re.findall(
        r"^\| ([a-z0-9_]+) \| ([^|]+) \| ((?:phase32c_\d{4}(?:, )?)+) \|$",
        pack(doc, "## Pack D", "### Proposed dispositions by group"),
        re.M,
    )
    pack_d: list[tuple[str, str, str]] = []
    for table, policies, findings in pack_d_rows:
        policy_names = [name.strip() for name in policies.split(",")]
        finding_ids = findings.split(", ")
        assert len(policy_names) == len(finding_ids), table
        pack_d.extend(
            (finding_id, table, policy)
            for finding_id, policy in zip(finding_ids, policy_names, strict=True)
        )

    assert len(pack_c) == 5
    assert len(pack_b) == 5
    assert len(pack_d) == 36
    assert "| 1 | C — principal scope | 5 findings, all high |" in doc
    assert "| 3 | B — initial state and transitions | 5 findings, all high |" in doc
    assert "| 4 | D — permissive overlap | 36 findings, all medium |" in doc

    placed = Counter(finding_id for finding_id, _table, _policy in pack_c)
    placed.update(finding_id for finding_id, _table, _policy in pack_b)
    placed.update(finding_id for finding_id, _table, _policy in pack_d)
    assert set(placed) == set(expected)
    assert all(count == 1 for count in placed.values())

    for finding_id, table, policy in pack_c + pack_b + pack_d:
        severity, expected_table, expected_policy = expected[finding_id]
        assert (table, policy) == (expected_table, expected_policy), finding_id
    assert all(expected[f][0] == "high" for f, _t, _p in pack_c + pack_b)
    assert all(expected[f][0] == "medium" for f, _t, _p in pack_d)

    mentioned = set(re.findall(r"phase32c_\d{4}", doc))
    assert mentioned <= set(expected)


def test_quoted_predicates_match_evidence_token_for_token() -> None:
    doc = read(SCOPING_PATH)
    by_name = {policy: row for (_table, policy), row in section02().items()}

    section_a = pack(doc, "## Pack A", "## Pack B")
    quoted_a = re.findall(
        r"^\| [a-z0-9_]+ \| ([a-z0-9_]+) \| `([^`]+)` \|$", section_a, re.M
    )
    assert len(quoted_a) == 10
    for policy, predicate in quoted_a:
        row = by_name[policy]
        assert squash(row["complete_using_expression"]) == squash(
            row["complete_with_check_expression"]
        )
        assert tokens(predicate) == tokens(row["complete_using_expression"]), policy

    section_c = pack(doc, "### Complete predicates", "### Proposed dispositions")
    quoted_c = re.findall(r"^\| ([a-z0-9_]+) \| `([^`]+)` \|$", section_c, re.M)
    assert len(quoted_c) == 5
    for policy, predicate in quoted_c:
        row = by_name[policy]
        if row["policy_command"] == "INSERT":
            expected = ["WITH", "CHECK", *tokens(row["complete_with_check_expression"])]
        else:
            expected = tokens(row["complete_using_expression"])
        assert tokens(predicate) == expected, policy

    section_b = pack(doc, "## Pack B", "## Pack D")
    quoted_b = re.findall(
        r"^\| phase32c_\d{4} \| [a-z0-9_]+ \| ([a-z0-9_]+) \| `([^`]+)` \|",
        section_b,
        re.M,
    )
    assert len(quoted_b) == 3
    for policy, predicate in quoted_b:
        row = by_name[policy]
        assert row["policy_command"] == "INSERT"
        assert tokens(predicate) == tokens(row["complete_with_check_expression"])


def test_pack_claims_are_backed_by_section05_and_section02() -> None:
    signals = {(row["policy_name"], row["operation_name"]): row for row in section05()}
    policies = section02()

    for policy in (
        "furnishing_request_select",
        "furnishing_request_design_version_select",
        "payment_select_customer",
        "refund_select_customer",
    ):
        assert signals[(policy, "SELECT")]["possible_cross_principal_read"] == "true"
    assert (
        signals[("service_request_insert_own", "INSERT")][
            "possible_cross_principal_write"
        ]
        == "true"
    )
    for policy in (
        "customer_profile_insert_own",
        "design_insert_own",
        "design_product_reference_write_own",
        "design_version_insert_own",
        "party_capability_write_own",
    ):
        assert signals[(policy, "INSERT")]["possible_owner_only_insert_check"] == "true"

    # The two policies observed outside the ledger carry no audit signal.
    for policy in ("service_request_update_engaged", "purchase_order_update_party"):
        assert all(
            signals[(policy, "UPDATE")][flag] == "false" for flag in SIGNAL_FLAGS
        )
    engaged = policies[("service_request", "service_request_update_engaged")]
    assert squash(engaged["complete_using_expression"]) == (
        "((customer_profile_id = current_customer_profile_id()) OR "
        "(marketplace_party_id = current_marketplace_party_id()))"
    )
    assert squash(engaged["complete_with_check_expression"]) == squash(
        engaged["complete_using_expression"]
    )
    party = policies[("purchase_order", "purchase_order_update_party")]
    assert squash(party["complete_using_expression"]) == (
        "(marketplace_party_id = current_marketplace_party_id())"
    )

    public_party = policies[("marketplace_party", "marketplace_party_select_public")]
    assert public_party["policy_roles"] == "{anon,authenticated}"
    assert squash(public_party["complete_using_expression"]) == (
        "(approval_state = 'approved'::party_approval_state)"
    )

    # party_capability is the only seller write without the approval helper.
    capability = policies[("party_capability", "party_capability_write_own")]
    assert "current_party_is_approved()" not in capability["complete_using_expression"]
    for table, policy, field in (
        ("offer", "offer_insert_own", "complete_with_check_expression"),
        ("offer", "offer_update_own_limited", "complete_using_expression"),
        ("custom_offering", "custom_offering_write_own", "complete_using_expression"),
    ):
        assert "current_party_is_approved()" in policies[(table, policy)][field]
