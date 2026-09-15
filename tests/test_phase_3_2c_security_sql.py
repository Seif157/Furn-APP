"""Static, fail-closed tests for the review-only Phase 3.2C package."""

import csv
import hashlib
import re
from collections import Counter
from pathlib import Path

from pglast import ast, parse_sql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = PROJECT_ROOT / "sql"
CORE_PATH = SQL_DIR / "phase-3.2c-security-hardening.sql"
PREFLIGHT_PATH = SQL_DIR / "phase-3.2c-security-hardening-preflight.sql"
VERIFY_PATH = SQL_DIR / "phase-3.2c-security-hardening-verify.sql"
DOC_PATH = PROJECT_ROOT / "docs" / "phase-3.2c-security-hardening.md"
EVIDENCE_DIR = PROJECT_ROOT / "docs" / "evidence" / "phase-3.2c"
SECTION03_PATH = EVIDENCE_DIR / "section-03-for-all.csv"
SECTION12_PATH = EVIDENCE_DIR / "section-12-findings.csv"

SECTION03_HEADERS = (
    "result_kind",
    "table_name",
    "policy_name",
    "policy_mode",
    "policy_roles",
    "complete_using_expression",
    "complete_with_check_expression",
    "current_for_all_policy_count",
    "result_detail",
)
SECTION12_HEADERS = (
    "finding_id",
    "severity",
    "table",
    "policy",
    "finding",
    "evidence",
    "recommended_decision",
    "migration_required",
    "human_business_decision_required",
    "finding_classification",
)
ALLOWED_DISPOSITIONS = {
    "remediated",
    "accepted_with_evidence",
    "audit_false_positive",
    "deferred_with_named_blocker",
}
FURNISHING_COLUMNS = (
    "id",
    "customer_profile_id",
    "address_id",
    "title",
    "requirements_description",
    "reference_image_urls",
    "budget_min",
    "budget_max",
    "requested_timing",
    "offer_deadline",
    "lifecycle_state",
    "created_at",
    "coarse_location",
)
FURNISHING_INSERT_COLUMNS = (
    "customer_profile_id",
    "address_id",
    "title",
    "requirements_description",
    "reference_image_urls",
    "budget_min",
    "budget_max",
    "requested_timing",
    "offer_deadline",
    "coarse_location",
)
FURNISHING_UPDATE_COLUMNS = (
    "address_id",
    "title",
    "requirements_description",
    "reference_image_urls",
    "budget_min",
    "budget_max",
    "requested_timing",
    "offer_deadline",
    "coarse_location",
)
TERMINAL_STATES = ("accepted", "withdrawn", "closed")
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
    SQL_DIR / "phase-3.2b-security-hardening-preflight.sql": (
        "bbeaa3a5a87079bdfcda2008f1d01a925875ba09cb570ac2908d4e68db9c8028"
    ),
    SQL_DIR / "phase-3.2b-security-hardening-verify.sql": (
        "79b4d303a0cb0852ea25307fa6f2a8da89555253ddc33dba9740f33b5cd0d411"
    ),
    SQL_DIR / "phase-3.2b-helper-function-definitions.sql": (
        "46f7479620441a9036296b049509a88961f29a751273bf09a58eef1adecab9bb"
    ),
    SQL_DIR / "phase-3.2b-supabase-admin-default-privileges-diagnostic.sql": (
        "1e5aa94b0a20801f806560c9703cbe89f3e1fe8bd90001276c43942706044cbc"
    ),
    SQL_DIR / "phase-3.2b-supabase-admin-default-privileges-optional.sql": (
        "df827163eeb7e333452086b7caecfb1b471eb727839450c6212f43b9a306f232"
    ),
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalized(path: Path) -> str:
    return re.sub(r"\s+", " ", read(path).lower()).strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_rows(
    path: Path,
    expected_headers: tuple[str, ...],
) -> list[dict[str, str]]:
    assert path.is_file(), f"missing evidence: {path}"
    with path.open(encoding="utf-8", newline="") as evidence:
        reader = csv.DictReader(evidence)
        assert tuple(reader.fieldnames or ()) == expected_headers
        rows = list(reader)
    assert all(None not in row for row in rows)
    assert all(tuple(row) == expected_headers for row in rows)
    return rows


def section03_policy_rows() -> list[dict[str, str]]:
    rows = csv_rows(SECTION03_PATH, SECTION03_HEADERS)
    return [row for row in rows if row["result_kind"] == "policy"]


def section12_rows() -> list[dict[str, str]]:
    return csv_rows(SECTION12_PATH, SECTION12_HEADERS)


def preflight_block(sql: str) -> str:
    start = sql.index("DO $phase32c_preflight$")
    marker = "$phase32c_preflight$;"
    end = sql.index(marker, start) + len(marker)
    return sql[start:end]


def policy_identity(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        row["table_name"],
        row["policy_name"],
        row["policy_mode"],
        row["policy_roles"],
    )


def finding_identity(
    row: dict[str, str],
) -> tuple[str, str, str, str, str]:
    return (
        row["finding_id"],
        row["severity"],
        row["table"],
        row["policy"],
        row["finding"],
    )


def document_policy_dispositions() -> list[tuple[str, str, str, str, str]]:
    pattern = re.compile(
        r"^\| ([a-z0-9_]+) \| ([a-z0-9_]+) \| "
        r"(PERMISSIVE|RESTRICTIVE) \| (\{[a-z_,]+\}) \| "
        r"([a-z_]+) \| ([^|]+) \|$",
        re.MULTILINE,
    )
    return [
        (table, policy, mode, roles, classification)
        for table, policy, mode, roles, classification, basis in pattern.findall(
            read(DOC_PATH)
        )
        if basis.strip()
    ]


def document_finding_dispositions() -> list[tuple[str, str, str, str, str, str]]:
    pattern = re.compile(
        r"^\| (phase32c_\d{4}) \| ([a-z]+) \| ([a-z0-9_]+) \| "
        r"([^|]+) \| ([a-z0-9_]+) \| ([a-z_]+) \| ([^|]+) \|$",
        re.MULTILINE,
    )
    return [
        (
            finding_id,
            severity,
            table,
            "" if policy.strip() == "—" else policy.strip(),
            finding,
            classification,
        )
        for (
            finding_id,
            severity,
            table,
            policy,
            finding,
            classification,
            basis,
        ) in pattern.findall(read(DOC_PATH))
        if basis.strip()
    ]


def test_every_phase32c_sql_artifact_parses() -> None:
    for path in (CORE_PATH, PREFLIGHT_PATH, VERIFY_PATH):
        assert parse_sql(read(path))


def test_preserved_readmes_and_phase32b_sql_are_byte_identical() -> None:
    for path, expected_digest in PRESERVED_DIGESTS.items():
        assert sha256(path) == expected_digest


def test_section03_evidence_schema_counts_summary_and_uniqueness() -> None:
    rows = csv_rows(SECTION03_PATH, SECTION03_HEADERS)
    policies = [row for row in rows if row["result_kind"] == "policy"]
    summaries = [row for row in rows if row["result_kind"] == "summary"]

    assert len(rows) == 20
    assert len(policies) == 19
    assert len(summaries) == 1
    assert len({tuple(row.items()) for row in rows}) == 20
    assert len({policy_identity(row) for row in policies}) == 19
    assert all(row["current_for_all_policy_count"] == "19" for row in rows)
    assert {row["result_kind"] for row in rows} == {"policy", "summary"}
    assert all(row["result_detail"] == "current_for_all_policy" for row in policies)
    assert all(row["policy_mode"] in {"PERMISSIVE", "RESTRICTIVE"} for row in policies)
    assert all(row["policy_roles"] for row in policies)
    assert all(row["complete_using_expression"] for row in policies)
    assert all(row["complete_with_check_expression"] for row in policies)
    assert summaries[0]["result_detail"] == "current_for_all_policies_listed_above"
    for nullable_summary_field in (
        "table_name",
        "policy_name",
        "complete_using_expression",
        "complete_with_check_expression",
    ):
        assert summaries[0][nullable_summary_field] == "null"
    assert summaries[0]["policy_mode"] == "null"
    assert summaries[0]["policy_roles"] == "null"


def test_section12_evidence_schema_count_types_and_uniqueness() -> None:
    rows = section12_rows()
    assert len(rows) == 122
    assert len({tuple(row.items()) for row in rows}) == 122
    assert len({finding_identity(row) for row in rows}) == 122
    assert [row["finding_id"] for row in rows] == [
        f"phase32c_{number:04d}" for number in range(1, 123)
    ]
    for row in rows:
        assert all(row[column] for column in SECTION12_HEADERS if column != "policy")
        assert row["migration_required"] in {"true", "false"}
        assert row["human_business_decision_required"] in {"true", "false"}
    assert {row["severity"] for row in rows} == {"critical", "high", "medium"}
    assert {row["finding_classification"] for row in rows} == {
        "static_risk_signal",
        "layered_control_hypothesis",
        "business_semantics_hypothesis",
    }
    assert {row["finding"] for row in rows} == {
        "literal_true_or_tautology",
        "marketplace_party_approval_policy_gap",
        "possible_cross_principal_read",
        "possible_cross_principal_write",
        "unexpected_admin_branch",
        "owner_only_insert_or_state_transition_risk",
        "overlapping_permissive_policies",
    }


def test_policy_dispositions_reconcile_source_bidirectionally() -> None:
    source_rows = section03_policy_rows()
    disposition_rows = document_policy_dispositions()
    source = {policy_identity(row) for row in source_rows}
    disposed = {
        (table, policy, mode, roles)
        for table, policy, mode, roles, _classification in disposition_rows
    }

    assert len(disposition_rows) == 19
    assert len(disposed) == 19
    assert source - disposed == set()
    assert disposed - source == set()
    assert all(row[4] in ALLOWED_DISPOSITIONS for row in disposition_rows)
    assert all(
        count == 1 for count in Counter(row[:4] for row in disposition_rows).values()
    )


def test_finding_dispositions_reconcile_source_bidirectionally() -> None:
    source_rows = section12_rows()
    disposition_rows = document_finding_dispositions()
    source = {finding_identity(row) for row in source_rows}
    disposed = {
        (finding_id, severity, table, policy, finding)
        for (
            finding_id,
            severity,
            table,
            policy,
            finding,
            _classification,
        ) in disposition_rows
    }

    assert len(disposition_rows) == 122
    assert len(disposed) == 122
    assert source - disposed == set()
    assert disposed - source == set()
    assert all(row[5] in ALLOWED_DISPOSITIONS for row in disposition_rows)
    assert all(
        count == 1 for count in Counter(row[:5] for row in disposition_rows).values()
    )


def test_reconciliation_detects_altered_missing_extra_and_duplicate_identities() -> (
    None
):
    source = {policy_identity(row) for row in section03_policy_rows()}
    disposed = {row[:4] for row in document_policy_dispositions()}
    removed = next(iter(disposed))
    altered = (
        removed[0],
        f"{removed[1]}_altered",
        removed[2],
        removed[3],
    )
    mutated = (disposed - {removed}) | {altered}

    assert source - mutated == {removed}
    assert mutated - source == {altered}
    duplicated = list(disposed) + [removed]
    assert len(duplicated) != len(set(duplicated))


def test_core_is_one_transaction_with_local_safeguards_and_postflight() -> None:
    sql = normalized(CORE_PATH)
    assert sql.count(" begin;") + sql.startswith("begin;") == 1
    assert sql.count(" commit;") == 1
    assert sql.endswith("commit;")
    preflight = sql.index("do $phase32c_preflight$")
    first_change = sql.index("create or replace function")
    postflight = sql.index("do $phase32c_postflight$")
    assert preflight < first_change < postflight < sql.rindex("commit;")
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
    assert standalone.count("BEGIN;") == 1
    assert standalone.count("ROLLBACK;") == 1
    assert "COMMIT;" not in standalone
    outside = standalone.replace(preflight_block(standalone), "").lower()
    for persistent in (
        "create policy",
        "drop policy",
        "create view",
        "create or replace function",
        "alter function",
        "grant ",
        "revoke ",
    ):
        assert persistent not in outside


def test_preflight_embeds_exact_section03_identity_set_with_bidirectional_except() -> (
    None
):
    block = preflight_block(read(CORE_PATH))
    identity_area = block[
        block.index("-- Exact set reconciliation") : block.index(
            "IF EXISTS (\n        SELECT 1\n        FROM (\n            VALUES"
        )
    ]
    embedded = set(
        re.findall(
            r"\('([a-z0-9_]+)'::name, '([a-z0-9_]+)'::name, "
            r"'(PERMISSIVE|RESTRICTIVE)'::text, "
            r"ARRAY\['([a-z_]+)'\]::name\[\]\)",
            identity_area,
        )
    )
    source = {
        (
            row["table_name"],
            row["policy_name"],
            row["policy_mode"],
            row["policy_roles"].strip("{}"),
        )
        for row in section03_policy_rows()
    }
    assert embedded == source
    assert len(re.findall(r"\bEXCEPT\b", identity_area)) == 2
    assert "<> 19" in identity_area


def test_preflight_validates_exact_furnishing_inventory_and_privilege_baseline() -> (
    None
):
    block = preflight_block(read(CORE_PATH))
    inventory = block[
        block.index(
            "-- Exact live-confirmed furnishing_request catalog signature."
        ) : block.index(
            "-- Exact live-confirmed effective INSERT/UPDATE privilege baseline."
        )
    ]
    assert inventory.count("::name,") == 13
    assert len(re.findall(r"\bEXCEPT\b", inventory)) == 2
    assert inventory.count("EXCEPT SELECT * FROM actual") == 1
    assert inventory.count("EXCEPT SELECT * FROM expected") == 1
    assert ") <> 13" in inventory
    assert "attribute.attnum::integer" in inventory
    assert "attribute.atttypid as type_oid" in inventory.lower()
    assert "attribute.atttypmod as type_modifier" in inventory.lower()
    assert "attribute.attnotnull as is_not_null" in inventory.lower()
    assert "attribute.attidentity as identity_kind" in inventory.lower()
    assert "attribute.attgenerated as generated_kind" in inventory.lower()
    for ordinal, column in enumerate(FURNISHING_COLUMNS, 1):
        assert f"({ordinal}, '{column}'::name," in inventory
    for exact_type in (
        "'pg_catalog.uuid'::pg_catalog.regtype",
        "'pg_catalog.text'::pg_catalog.regtype",
        "'pg_catalog.text[]'::pg_catalog.regtype",
        "'pg_catalog.numeric'::pg_catalog.regtype",
        "'pg_catalog.timestamptz'::pg_catalog.regtype",
        "'public.furnishing_request_state'::pg_catalog.regtype",
        "'numeric(12,2)'::text",
    ):
        assert exact_type in inventory
    for exact_default in (
        "'gen_random_uuid()'::text",
        "'''draft''::furnishing_request_state'::text",
        "'now()'::text",
    ):
        assert exact_default in inventory
    assert inventory.count("''::pg_catalog.\"char\"") == 26

    privilege_baseline = block[
        block.index(
            "-- Exact live-confirmed effective INSERT/UPDATE privilege baseline."
        ) : block.index("IF ARRAY(", block.index("-- Exact live-confirmed effective"))
    ]
    assert privilege_baseline.count("('id'::name)") == 1
    assert all(
        f"('{column}'::name)" in privilege_baseline for column in FURNISHING_COLUMNS
    )
    assert "(anon_role_oid, false, false)" in privilege_baseline
    assert "(authenticated_role_oid, true, true)" in privilege_baseline
    assert "(service_role_oid, true, true)" in privilege_baseline
    assert "has_column_privilege" in privilege_baseline
    assert "furnishing_request privilege baseline drift" in privilege_baseline
    assert "customer-editable furnishing column whitelist is missing" not in block


def test_public_review_uses_anon_column_grants_and_no_view_or_definer_reader() -> None:
    sql = normalized(CORE_PATH)
    assert "create view public.public_review" not in sql
    assert "security_invoker = false" not in sql
    assert "alter view public.public_review owner to postgres" not in sql
    assert "drop policy review_select_public on public.review" in sql
    assert "revoke select on table public.review from public, anon" in sql
    assert (
        "grant select ( id, target_kind, target_product_id, "
        "target_marketplace_party_id, rating, comment, created_at ) "
        "on table public.review to anon"
    ) in sql
    grant = sql[
        sql.index("grant select (") : sql.index(
            "create policy phase32c_review_anon_safe_read"
        )
    ]
    assert "customer_profile_id" not in grant
    assert "target_service_request_id" not in grant


def test_review_anon_policy_is_complete_and_not_shared_with_authenticated() -> None:
    sql = normalized(CORE_PATH)
    policy = sql[
        sql.index("create policy phase32c_review_anon_safe_read") : sql.index(
            "create policy phase32c_review_authenticated_read_guard"
        )
    ]
    assert "for select to anon" in policy
    assert "to authenticated" not in policy
    assert "target_kind::text = 'product'" in policy
    assert "target_kind::text = 'marketplace_party'" in policy
    assert policy.count("target_service_request_id is null") == 2
    assert (
        "reviewed_product.lifecycle_state = 'published'::public.product_state" in policy
    )
    assert policy.count("approval_state = 'approved'::public.party_approval_state") == 2
    assert "product_category.is_active" in policy
    assert "available_color.stock_quantity > 0" in policy
    assert "target_kind::text = 'service_request'" not in policy


def test_review_authenticated_guard_is_restrictive_owner_or_admin() -> None:
    sql = normalized(CORE_PATH)
    policy = sql[
        sql.index("create policy phase32c_review_authenticated_read_guard") : sql.index(
            "-- replace literal-true service-directory"
        )
    ]
    assert "as restrictive for select to authenticated" in policy
    assert "customer_profile_id = public.current_customer_profile_id()" in policy
    assert "or public.is_admin()" in policy
    assert "to anon" not in policy


def test_service_directory_replaces_literal_true_with_separate_paths() -> None:
    sql = normalized(CORE_PATH)
    service = sql[
        sql.index("drop policy service_type_select_public") : sql.index(
            "-- split customer furnishing"
        )
    ]
    assert "drop policy party_capability_select" in service
    assert service.count("for select to anon") == 2
    assert service.count("for select to authenticated") == 4
    assert "using (is_active)" in service
    assert "capability_party.approval_state" in service
    assert "capability_service.is_active" in service
    assert "phase32c_party_capability_owner_read" in service
    assert "public.current_marketplace_party_id()" in service
    assert "phase32c_party_capability_admin_read" in service
    assert "public.is_admin()" in service
    assert "using (true)" not in service


def test_furnishing_policies_split_operations_and_lock_terminal_states() -> None:
    sql = normalized(CORE_PATH)
    furnishing = sql[
        sql.index("drop policy furnishing_request_write_own") : sql.index(
            "create or replace function public.open_furnishing_request"
        )
    ]
    assert furnishing.count("create policy") == 3
    assert furnishing.count("for insert") == 1
    assert furnishing.count("for update") == 1
    assert furnishing.count("for delete") == 1
    assert "for select" not in furnishing
    assert "lifecycle_state = 'draft'::public.furnishing_request_state" in furnishing
    assert furnishing.count("'draft'::public.furnishing_request_state") == 4
    assert furnishing.count("'open'::public.furnishing_request_state") == 3
    assert furnishing.count("from public.address as request_address") == 2
    assert furnishing.count("request_address.id = furnishing_request.address_id") == 2
    assert (
        furnishing.count(
            "request_address.customer_profile_id = public.current_customer_profile_id()"
        )
        == 2
    )
    for terminal_state in ("accepted", "withdrawn", "closed"):
        assert f"'{terminal_state}'" not in furnishing
    assert "or true" not in furnishing

    assert (
        "revoke insert, update on table public.furnishing_request from authenticated"
    ) in furnishing
    column_revoke = re.search(
        r"revoke insert \((.*?)\), update \((.*?)\) "
        r"on table public\.furnishing_request from authenticated",
        furnishing,
    )
    assert column_revoke is not None
    assert tuple(re.findall(r"[a-z_]+", column_revoke.group(1))) == FURNISHING_COLUMNS
    assert tuple(re.findall(r"[a-z_]+", column_revoke.group(2))) == FURNISHING_COLUMNS

    insert_grant = re.search(
        r"grant insert \((.*?)\) on table public\.furnishing_request "
        r"to authenticated",
        furnishing,
    )
    update_grant = re.search(
        r"grant update \((.*?)\) on table public\.furnishing_request "
        r"to authenticated",
        furnishing,
    )
    assert insert_grant is not None
    assert update_grant is not None
    assert tuple(re.findall(r"[a-z_]+", insert_grant.group(1))) == (
        FURNISHING_INSERT_COLUMNS
    )
    assert tuple(re.findall(r"[a-z_]+", update_grant.group(1))) == (
        FURNISHING_UPDATE_COLUMNS
    )
    acl_section = furnishing[furnishing.index("revoke insert, update on table") :]
    assert "from anon" not in acl_section
    assert "from service_role" not in acl_section
    assert "to anon" not in acl_section
    assert "to service_role" not in acl_section


OWNER_PREDICATE = "customer_profile_id = public.current_customer_profile_id()"
DRAFT_PREDICATE = "lifecycle_state = 'draft'::public.furnishing_request_state"
DRAFT_MEMBER = "'draft'::public.furnishing_request_state"
OPEN_MEMBER = "'open'::public.furnishing_request_state"
ADDRESS_SOURCE = "from public.address as request_address"
ADDRESS_LINK = "request_address.id = furnishing_request.address_id"
ADDRESS_OWNER = (
    "request_address.customer_profile_id = public.current_customer_profile_id()"
)
# Exact predicate occurrence counts for every furnishing policy. The owner
# predicate is counted once for each top-level owner check plus once for the
# address-ownership subquery, so removing any single copy changes a count.
FURNISHING_POLICY_SIGNATURES: dict[str, dict[str, int]] = {
    "phase32c_furnishing_request_insert_own": {
        OWNER_PREDICATE: 2,
        DRAFT_PREDICATE: 1,
        DRAFT_MEMBER: 1,
        OPEN_MEMBER: 0,
        ADDRESS_SOURCE: 1,
        ADDRESS_LINK: 1,
        ADDRESS_OWNER: 1,
        " and ": 3,
    },
    "phase32c_furnishing_request_update_own": {
        OWNER_PREDICATE: 3,
        DRAFT_PREDICATE: 0,
        DRAFT_MEMBER: 2,
        OPEN_MEMBER: 2,
        ADDRESS_SOURCE: 1,
        ADDRESS_LINK: 1,
        ADDRESS_OWNER: 1,
        " and ": 4,
    },
    "phase32c_furnishing_request_delete_own": {
        OWNER_PREDICATE: 1,
        DRAFT_PREDICATE: 0,
        DRAFT_MEMBER: 1,
        OPEN_MEMBER: 1,
        ADDRESS_SOURCE: 0,
        ADDRESS_LINK: 0,
        ADDRESS_OWNER: 0,
        " and ": 1,
    },
}


def furnishing_policy_bodies(sql: str) -> dict[str, str]:
    section = sql[
        sql.index("create policy phase32c_furnishing_request_insert_own") : sql.index(
            "revoke insert, update on table public.furnishing_request"
        )
    ]
    # Drop the trailing ACL-normalization comment so only policy text is scored.
    section = section[: section.rindex(";") + 1]
    bodies: dict[str, str] = {}
    names = list(FURNISHING_POLICY_SIGNATURES)
    for index, name in enumerate(names):
        begin = section.index(f"create policy {name}")
        finish = (
            section.index(f"create policy {names[index + 1]}")
            if index + 1 < len(names)
            else len(section)
        )
        bodies[name] = section[begin:finish]
    return bodies


def is_narrow_policy(name: str, candidate: str) -> bool:
    signature = FURNISHING_POLICY_SIGNATURES[name]
    return (
        all(candidate.count(needle) == count for needle, count in signature.items())
        and " or " not in candidate
        and not any(f"'{state}'" in candidate for state in TERMINAL_STATES)
    )


def test_furnishing_predicate_regression_rejects_removal_or_broadening() -> None:
    bodies = furnishing_policy_bodies(normalized(CORE_PATH))
    assert list(bodies) == list(FURNISHING_POLICY_SIGNATURES)
    for name, body in bodies.items():
        assert is_narrow_policy(name, body), name
        for needle, count in FURNISHING_POLICY_SIGNATURES[name].items():
            if count == 0:
                continue
            # Removing any single predicate copy, including one of the
            # duplicated owner checks, must be detected.
            for occurrence in range(count):
                position = -1
                for _ in range(occurrence + 1):
                    position = body.index(needle, position + 1)
                mutated = body[:position] + body[position + len(needle) :]
                assert not is_narrow_policy(name, mutated), (name, needle, occurrence)
        # Broadening by disjunction, tautology, or terminal-state admission
        # must be detected.
        broadenings = [
            body.replace(" and ", " or ", 1),
            body.replace(" );", " or true );", 1),
            body + " or 1 = 1",
            body.replace(DRAFT_MEMBER, "'accepted'::public.furnishing_request_state"),
        ]
        if OPEN_MEMBER in body:
            broadenings.extend(
                body.replace(OPEN_MEMBER, f"'{state}'::public.furnishing_request_state")
                for state in ("withdrawn", "closed")
            )
        for broadening in broadenings:
            assert broadening != body, name
            assert not is_narrow_policy(name, broadening), name
    # Owner and address ownership are required on both INSERT and UPDATE.
    for name in (
        "phase32c_furnishing_request_insert_own",
        "phase32c_furnishing_request_update_own",
    ):
        assert FURNISHING_POLICY_SIGNATURES[name][ADDRESS_OWNER] == 1
        assert FURNISHING_POLICY_SIGNATURES[name][OWNER_PREDICATE] >= 2


def test_transition_functions_are_exact_uniform_and_narrow() -> None:
    sql = normalized(CORE_PATH)
    open_function = sql[
        sql.index(
            "create or replace function public.open_furnishing_request"
        ) : sql.index("create or replace function public.withdraw_furnishing_request")
    ]
    withdraw_function = sql[
        sql.index(
            "create or replace function public.withdraw_furnishing_request"
        ) : sql.index("-- preserve the invoker-rights financial view")
    ]
    for function in (open_function, withdraw_function):
        body = function[function.index("as $function$") : function.index("$function$;")]
        assert "returns pg_catalog.boolean" in function
        assert (
            "language plpgsql volatile security definer set search_path = ''"
            in function
        )
        assert 'update "public".furnishing_request as request_row' in function
        assert "from public.customer_profile as customer" in function
        assert "customer.user_id = auth.uid()" in function
        assert "get diagnostics affected_rows = row_count" in function
        assert "return affected_rows = 1" in function
        assert "from public, anon, authenticated, service_role" in function
        assert "to authenticated, service_role" in function
        assert re.findall(r"\bset\s+([a-z_]+)\s*=", body) == ["lifecycle_state"]
        assignment = body.split("set lifecycle_state", 1)[1].split("where", 1)[0]
        assert "," not in assignment
        assert "or true" not in body
    assert "set lifecycle_state = 'open'" in open_function
    assert "lifecycle_state::text = 'draft'" in open_function
    for forbidden in ("withdrawn", "accepted", "closed"):
        assert f"'{forbidden}'" not in open_function
    assert "set lifecycle_state = 'withdrawn'" in withdraw_function
    assert "lifecycle_state::text = 'open'" in withdraw_function
    for forbidden in ("draft", "accepted", "closed"):
        assert f"'{forbidden}'" not in withdraw_function


def test_transition_postflight_checks_directions_and_exact_grants() -> None:
    sql = normalized(CORE_PATH)
    postflight = sql[sql.index("do $phase32c_postflight$") :]
    assert "transition_old_state := 'draft'" in postflight
    assert "transition_new_state := 'open'" in postflight
    assert "transition_old_state := 'open'" in postflight
    assert "transition_new_state := 'withdrawn'" in postflight
    assert "transition_forbidden_states" in postflight
    assert "get diagnostics affected_rows = row_count" in postflight
    assert "length('set lifecycle_state') = 1" in postflight
    assert "split_part" in postflight
    assert "not like '%or true%'" in postflight
    assert "acl.grantee not in" in postflight
    assert "acl.is_grantable" in postflight


def test_helper_financial_role_storage_and_force_guards_remain() -> None:
    sql = normalized(CORE_PATH)
    assert "set search_path = ''" in sql
    assert "from public.customer_profile as customer" in sql
    assert "where customer.user_id = auth.uid()" in sql
    assert "from public, anon, authenticated, service_role" in sql
    finance = sql[
        sql.index(
            "revoke all privileges on table public.order_financial_position"
        ) : sql.index("do $phase32c_postflight$")
    ]
    assert "from public, anon, authenticated" in finance
    assert "to authenticated" in finance
    assert "service_role" not in finance
    assert "create view public.order_financial_position" not in sql
    assert "storage." not in sql
    assert "alter default privileges" not in sql
    assert "force row level security" not in sql
    assert "enable row level security" not in sql
    assert "to_regrole('public')" not in sql
    assert "acl.grantee = 0" in sql


def test_core_has_no_top_level_application_row_dml_or_unreviewed_dynamic_sql() -> None:
    statements = parse_sql(read(CORE_PATH))
    forbidden = (ast.InsertStmt, ast.UpdateStmt, ast.DeleteStmt)
    assert not any(isinstance(statement.stmt, forbidden) for statement in statements)
    sql = normalized(CORE_PATH)
    assert not re.search(r"\bexecute\s+(?:format|\$|')", sql)
    assert "regexp_replace" not in sql


def test_verifier_is_twenty_select_only_sections_with_uniform_shape() -> None:
    verify = read(VERIFY_PATH)
    statements = parse_sql(verify)
    assert len(statements) == 20
    assert all(isinstance(statement.stmt, ast.SelectStmt) for statement in statements)
    assert len(re.findall(r"(?m)^-- (?:0[1-9]|1[0-9]|20)\.", verify)) == 20
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


def test_verifier_covers_corrected_review_lifecycle_and_preserved_controls() -> None:
    verify = normalized(VERIFY_PATH)
    for marker in (
        "review_anon_column_grants",
        "review_anon_policy_eligibility",
        "review_service_and_malformed_rows_excluded",
        "review_authenticated_owner_admin_guard",
        "service_type_active_only",
        "party_capability_public_scope",
        "service_directory_owner_admin_paths",
        "furnishing_request_exact_inventory",
        "furnishing_request_operation_policies",
        "furnishing_request_lifecycle_and_address_predicates",
        "furnishing_transition_definitions",
        "furnishing_transition_grants",
        "furnishing_request_exact_column_privileges",
        "financial_view_authenticated_select_only",
        "phase32b_catalogue_policies_unchanged",
        "service_role_functional",
        "client_role_separation",
        "unexpected_public_privileges",
        "managed_storage_default_acl_unchanged",
    ):
        assert marker in verify
    assert "security_invoker=false" not in verify
    assert "public.public_review" not in verify


def test_verifier_checks_inventory_and_exact_three_role_privilege_signature() -> None:
    verify = normalized(VERIFY_PATH)
    inventory = verify[verify.index("-- 09.") : verify.index("-- 10.")]
    assert inventory.count("::name,") == 13
    assert "attribute.attidentity as identity_kind" in inventory
    assert "attribute.attgenerated as generated_kind" in inventory
    assert inventory.count("except") == 2
    assert "expected_count = 13" in inventory
    assert "actual_count = 13" in inventory

    privileges = verify[verify.index("-- 14.") : verify.index("-- 15.")]
    assert "'anon'::text" in privileges
    assert "'authenticated'::text" in privileges
    assert "'service_role'::text" in privileges
    assert "99::bigint as expected_count" in privileges
    assert "78" in privileges
    assert privileges.count("except") == 2
    assert "acl.is_grantable" in privileges
    assert "has_table_privilege" in privileges
    assert all(f"'{column}'::name" in privileges for column in FURNISHING_COLUMNS)


def test_storage_verification_is_exact_and_version_aware() -> None:
    verify = read(VERIFY_PATH)
    section = verify[verify.index("-- 20.") :]
    assert section.count("('anon'::name)") == 1
    assert section.count("('authenticated'::name)") == 1
    assert section.count("('service_role'::name)") == 1
    assert "('S'::pg_catalog.\"char\", 's'::pg_catalog.\"char\"" in section
    assert "object_type.acldefault_object_type" in section
    assert "current_setting('server_version_num')::integer >= 170000" in section
    assert section.count("EXCEPT") == 2
    assert "acl.is_grantable" in section


def test_document_records_architectures_inventory_allowlists_and_review_gate() -> None:
    doc = read(DOC_PATH)
    assert "owner-rights" in doc
    assert "public_review" in doc
    assert "GET /v1/reviews/public" in doc
    assert "must query Supabase with the anonymous role" in doc
    assert "draft → open" in doc
    assert "open → withdrawn" in doc
    assert "### Sanitized live diagnostic" in doc
    assert "### Exact deployed inventory" in doc
    assert "### Approved authenticated column privileges" in doc
    assert "### RLS and address ownership" in doc
    assert "### Lifecycle transition matrix" in doc
    assert "authenticated and service_role each had effective INSERT/UPDATE" in doc
    assert "explicitly revokes column-level INSERT and UPDATE across all 13" in doc
    assert "foreign key by itself would not prevent" in doc
    assert "The inventory blocker is resolved." in doc
    assert "all 20 read-only verification sections" in doc
    for column in FURNISHING_COLUMNS:
        assert f"`{column}`" in doc
    assert "customer-editable furnishing column whitelist is missing" not in doc
    assert "Human security review required; not approved for deployment." in doc
