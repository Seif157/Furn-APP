"""Static, fail-closed tests for the review-only Phase 3.2D package."""

import hashlib
import re
from collections import Counter
from pathlib import Path

from pglast import ast, parse_sql

from tests import phase_3_2d_package as package

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = PROJECT_ROOT / "sql"
DOCS = PROJECT_ROOT / "docs"
CORE_PATH = package.CORE_PATH
PREFLIGHT_PATH = package.PREFLIGHT_PATH
VERIFY_PATH = package.VERIFY_PATH
DOC_PATH = DOCS / "phase-3.2d-security-hardening.md"
LEDGER_32C_PATH = DOCS / "phase-3.2c-security-hardening.md"
STATUS = "Human security review required; not approved for deployment."

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
    # Re-pinned 2026-09-18 with the user's approval after the first live
    # preflight exposed three authoring bugs: unqualified relation names under
    # search_path = pg_catalog, the review target-kind labels in the wrong
    # order, and three policies expected on role public instead of the live
    # {anon,authenticated}. Each fix matches the recorded live evidence.
    # Re-pinned again the same evening after the first live run of the
    # migration failed with 42704: pg_catalog.boolean and pg_catalog.integer
    # are not type names (bool and int4 are), and an empty search_path is
    # stored as search_path="" so exact matches on 'search_path=' now accept
    # both spellings, as the applied 3.2B package does. And once more when the
    # next run reached the postflight: aclexplode(COALESCE(attacl, ARRAY[]))
    # fails with 22023 because ARRAY[] is zero-dimensional; aclexplode(attacl)
    # means the same and works.
    SQL_DIR / "phase-3.2c-security-hardening.sql": (
        "8b04c44d19dcd2083e96f90321f5685758736295801be4a012cd9778b3736a1b"
    ),
    SQL_DIR / "phase-3.2c-security-hardening-preflight.sql": (
        "97054ae7eb8d57df6798915166db71853b2092ecedd5bfbceae25f27a9c6f02c"
    ),
    SQL_DIR / "phase-3.2c-security-hardening-verify.sql": (
        "384966e66f108141fd33c63508aac6833b19491b57f52985ad6728add57b673f"
    ),
    SQL_DIR / "phase-3.2c-rls-policy-audit.sql": (
        "3e3d0f36e3482877bc02c8ead12ea2ceda402c9838966e45b1324b4bed1e3e98"
    ),
}

NEVER_INSERTABLE = ("id", "created_at", "lifecycle_state", "placed_at")
NEVER_UPDATABLE = NEVER_INSERTABLE + (
    "customer_profile_id",
    "marketplace_party_id",
    "cart_id",
    "offer_id",
    "furnishing_request_id",
    "product_color_id",
    "accepted_at",
    "completed_at",
    "cancelled_at",
    "price",
    "user_id",
    "approval_state",
    "state_reason",
)
FUNCTION_SET_LISTS = {
    "cancel_service_request": ["lifecycle_state"],
    "accept_service_request": [
        "lifecycle_state",
        "marketplace_party_id",
        "accepted_at",
        "price",
    ],
    "start_service_request": ["lifecycle_state"],
    "complete_service_request": ["lifecycle_state", "completed_at"],
    "advance_purchase_order": ["lifecycle_state"],
    "cancel_purchase_order": ["lifecycle_state", "cancelled_at"],
}
FUNCTION_DIRECTIONS = {
    "cancel_service_request": (
        "pending",
        "cancelled",
        ("accepted", "in_progress", "completed"),
    ),
    "accept_service_request": (
        "pending",
        "accepted",
        ("in_progress", "completed", "cancelled"),
    ),
    "start_service_request": (
        "accepted",
        "in_progress",
        ("pending", "completed", "cancelled"),
    ),
    "complete_service_request": (
        "in_progress",
        "completed",
        ("pending", "accepted", "cancelled"),
    ),
    "cancel_purchase_order": (
        "pending",
        "cancelled",
        ("confirmed", "preparing", "out_for_delivery", "delivered"),
    ),
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalized(path: Path) -> str:
    return re.sub(r"\s+", " ", read(path).lower()).strip()


def preflight_block(sql: str) -> str:
    start = sql.index("DO $phase32d_preflight$")
    marker = "$phase32d_preflight$;"
    end = sql.index(marker, start) + len(marker)
    return sql[start:end]


def policy_bodies(sql: str) -> dict[str, str]:
    """Normalized text of every CREATE POLICY statement keyed by policy name."""
    bodies: dict[str, str] = {}
    for match in re.finditer(r"create policy (phase32d_[a-z0-9_]+) on public\.", sql):
        start = match.start()
        end = sql.index(";", start) + 1
        bodies[match.group(1)] = sql[start:end]
    return bodies


def function_bodies(sql: str) -> dict[str, str]:
    bodies: dict[str, str] = {}
    for name in FUNCTION_SET_LISTS:
        start = sql.index(f"create or replace function public.{name}(")
        end = sql.index("$function$;", start) + len("$function$;")
        bodies[name] = sql[start:end]
    return bodies


# --------------------------------------------------------------------------
# Generation, structure, and preservation
# --------------------------------------------------------------------------


def test_every_phase32d_sql_artifact_parses() -> None:
    for path in (CORE_PATH, PREFLIGHT_PATH, VERIFY_PATH):
        assert parse_sql(read(path))


def test_sql_files_are_byte_identical_to_the_evidence_generator() -> None:
    for path, expected in package.build().items():
        assert read(path) == expected, path.name


def test_preserved_phase32b_and_phase32c_artifacts_are_byte_identical() -> None:
    for path, digest in PRESERVED_DIGESTS.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, path.name


def test_core_is_one_transaction_with_local_safeguards_and_postflight() -> None:
    sql = normalized(CORE_PATH)
    assert sql.startswith("/*")
    assert sql.count(" begin;") == 1
    assert sql.count(" commit;") == 1
    assert sql.endswith("commit;")
    assert "rollback" not in sql
    preflight = sql.index("do $phase32d_preflight$")
    first_change = sql.index("drop policy address_write_own")
    postflight = sql.index("do $phase32d_postflight$")
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
        "create or replace function",
        "alter function",
        "grant ",
        "revoke ",
    ):
        assert persistent not in outside


def test_core_has_no_top_level_application_row_dml_or_unreviewed_statements() -> None:
    allowed = (
        ast.TransactionStmt,
        ast.VariableSetStmt,
        ast.DoStmt,
        ast.CreatePolicyStmt,
        ast.DropStmt,
        ast.GrantStmt,
        ast.CreateFunctionStmt,
        ast.AlterFunctionStmt,
        ast.AlterOwnerStmt,
    )
    for raw in parse_sql(read(CORE_PATH)):
        assert isinstance(raw.stmt, allowed), type(raw.stmt).__name__
    sql = normalized(CORE_PATH)
    for forbidden in (
        "storage.",
        "alter default privileges",
        "force row level security",
        "enable row level security",
        "to_regrole('public')",
        "create view",
        "alter table",
        "insert into",
        "delete from",
        "truncate",
    ):
        assert forbidden not in sql, forbidden
    assert "acl.grantee = 0" in sql


# --------------------------------------------------------------------------
# Preflight content
# --------------------------------------------------------------------------


def test_preflight_requires_applied_phase32c_and_no_prior_phase32d_objects() -> None:
    block = preflight_block(read(CORE_PATH)).lower()
    for required in (
        "phase32c_furnishing_request_insert_own",
        "phase32c_review_anon_safe_read",
        "phase32c_party_capability_owner_read",
        "public.open_furnishing_request(pg_catalog.uuid)",
        "public.withdraw_furnishing_request(pg_catalog.uuid)",
    ):
        assert required in block
    assert "'furnishing_request_write_own'" in block
    assert "requires the applied phase 3.2c migration" in block
    assert "policy.policyname like 'phase32d\\_%'" in block
    assert "phase 3.2d policies already exist" in block
    assert "phase 3.2d function already exists" in block
    for signature in package.TRANSITION_FUNCTIONS:
        assert f"'public.{signature}'".lower() in block


def test_preflight_embeds_evidence_derived_blocks_with_bidirectional_except() -> None:
    block = preflight_block(read(CORE_PATH))
    assert package.inventory_row_count() == 104
    assert package.privilege_row_count() == 312
    assert package.inventory_values() in block
    assert package.privilege_values(package.baseline_privileges()) in block
    assert package.for_all_values() in block
    assert package.replaced_policy_values() in block
    inventory = block[block.index("-- Exact live-confirmed column signatures") :]
    inventory = inventory[: inventory.index("column inventory drift")]
    assert len(re.findall(r"\bEXCEPT\b", inventory)) == 2
    assert f"<> {package.inventory_row_count()}" in inventory
    assert "attribute.attidentity <> ''" in inventory
    assert "attribute.atttypid::pg_catalog.regtype" in inventory
    assert "attribute.attgenerated" in inventory
    baseline = block[block.index("-- Exact effective privilege baseline") :]
    baseline = baseline[: baseline.index("privilege baseline drift")]
    assert baseline.count("has_column_privilege") == 3
    assert baseline.count("has_table_privilege") == 4
    assert (
        len(
            re.findall(
                r"\bEXCEPT\b",
                block[
                    block.index("-- Exact FOR ALL identity set") : block.index(
                        "FOR ALL identity drift"
                    )
                ],
            )
        )
        == 2
    )
    assert "<> 18" in block
    assert "regexp_replace(" in block
    assert "IS DISTINCT FROM expected.using_expression" in block
    assert "IS DISTINCT FROM expected.check_expression" in block


def test_replaced_policies_match_section02_exactly() -> None:
    rows = package.policies_to_replace()
    assert len(rows) == 13
    names = {policy for _table, policy, *_ in rows}
    expected = {
        policy for names_ in package.DROPPED_POLICIES.values() for policy in names_
    }
    assert names == expected
    for _table, policy, cmd, roles, using, check in rows:
        assert roles == "{authenticated}", policy
        if cmd == "ALL":
            assert using == check, policy
        assert "or true" not in using.lower()
    sql = normalized(CORE_PATH)
    for table, names_ in package.DROPPED_POLICIES.items():
        for policy in names_:
            assert f"drop policy {policy} on public.{table}" in sql, policy
    assert sql.count("drop policy ") == 13


def test_preflight_pins_constraints_enums_and_referenced_columns() -> None:
    block = preflight_block(read(CORE_PATH))
    for constraint in (
        "cart_customer_unique",
        "cart_line_unique_per_color",
        "customer_profile_user_unique",
        "marketplace_party_user_unique",
        "review_exactly_one_target",
        "service_request_executor_when_claimed",
        "purchase_order_cancelled_timestamp",
        "purchase_order_custom_offering_fk",
        "furnishing_request_address_fk",
    ):
        assert f"'{constraint}'::name" in block
    assert (
        "ARRAY['pending', 'accepted', 'in_progress', 'completed', 'cancelled']::text[]"
        in block
    )
    assert (
        "ARRAY['pending', 'confirmed', 'preparing', 'out_for_delivery', "
        "'delivered', 'cancelled']::text[]" in block
    )
    for column in (
        "('public.product_color'::pg_catalog.regclass, 'stock_quantity'::name)",
        "('public.design'::pg_catalog.regclass, 'originating_user_id'::name)",
        "('public.order_line_item'::pg_catalog.regclass, 'product_id'::name)",
        "('public.furnishing_request'::pg_catalog.regclass, 'address_id'::name)",
    ):
        assert column in block


# --------------------------------------------------------------------------
# Allowlists and grants
# --------------------------------------------------------------------------


def test_allowlists_never_expose_immutable_or_state_columns() -> None:
    for table, allowed in package.INSERT_ALLOWLIST.items():
        for column in allowed:
            assert column not in NEVER_INSERTABLE, (table, column)
            assert column in package.all_column_names(table), (table, column)
    for table, allowed in package.UPDATE_ALLOWLIST.items():
        for column in allowed:
            assert column not in NEVER_UPDATABLE, (table, column)
            assert column in package.all_column_names(table), (table, column)
    assert "cart" not in package.INSERT_ALLOWLIST
    assert "cart" not in package.UPDATE_ALLOWLIST
    assert "furnishing_request_design_version" not in package.INSERT_ALLOWLIST
    assert "purchase_order" not in package.INSERT_ALLOWLIST
    assert package.UPDATE_ALLOWLIST["purchase_order"] == ("notes",)
    assert package.UPDATE_ALLOWLIST["cart_line"] == ("quantity",)
    assert "review" not in package.UPDATE_ALLOWLIST
    assert "party_capability" not in package.UPDATE_ALLOWLIST
    assert "design_product_reference" not in package.UPDATE_ALLOWLIST
    assert "marketplace_party" not in package.INSERT_ALLOWLIST


def test_every_touched_table_is_fully_revoked_then_regranted_exactly() -> None:
    sql = normalized(CORE_PATH)
    for table in package.TOUCHED_TABLES:
        if table == "marketplace_party":
            continue
        assert (
            f"revoke insert, update on table public.{table} from authenticated" in sql
        )
        every = package.all_column_names(table)
        revoke = re.search(
            rf"revoke insert \(([^)]*)\), update \(([^)]*)\) on table public\.{table} "
            r"from authenticated",
            sql,
        )
        assert revoke is not None, table
        assert tuple(re.findall(r"[a-z_0-9]+", revoke.group(1))) == every, table
        assert tuple(re.findall(r"[a-z_0-9]+", revoke.group(2))) == every, table
        insert_grant = re.search(
            rf"grant insert \(([^)]*)\) on table public\.{table} to authenticated", sql
        )
        update_grant = re.search(
            rf"grant update \(([^)]*)\) on table public\.{table} to authenticated", sql
        )
        if table in package.INSERT_ALLOWLIST:
            assert insert_grant is not None, table
            assert (
                tuple(re.findall(r"[a-z_0-9]+", insert_grant.group(1)))
                == (package.INSERT_ALLOWLIST[table])
            )
        else:
            assert insert_grant is None, table
        if table in package.UPDATE_ALLOWLIST:
            assert update_grant is not None, table
            assert (
                tuple(re.findall(r"[a-z_0-9]+", update_grant.group(1)))
                == (package.UPDATE_ALLOWLIST[table])
            )
        else:
            assert update_grant is None, table


def test_no_role_other_than_authenticated_gains_privileges_except_party_columns() -> (
    None
):
    sql = normalized(CORE_PATH)
    changes = sql[
        sql.index("drop policy address_write_own") : sql.index(
            "do $phase32d_postflight$"
        )
    ]
    grants = re.findall(r"grant (.*?) to ([a-z_, ]+);", changes)
    for privilege, grantees in grants:
        names = {name.strip() for name in grantees.split(",")}
        if privilege.startswith("execute on function"):
            assert names == {"authenticated", "service_role"}, privilege
        elif "on table public.marketplace_party" in privilege:
            assert names in ({"anon"}, {"authenticated"}), privilege
            assert privilege.startswith("select (")
        else:
            assert names == {"authenticated"}, privilege
    assert "to public" not in changes
    assert "to service_role" not in changes.replace(
        "to authenticated, service_role", ""
    )
    party = changes[changes.index("revoke select on table public.marketplace_party") :]
    anon = re.search(
        r"grant select \(([^)]*)\) on table public\.marketplace_party to anon", party
    )
    auth = re.search(
        r"grant select \(([^)]*)\) on table public\.marketplace_party to authenticated",
        party,
    )
    assert anon is not None and auth is not None
    assert tuple(re.findall(r"[a-z_]+", anon.group(1))) == package.PARTY_ANON_SELECT
    assert (
        tuple(re.findall(r"[a-z_]+", auth.group(1)))
        == package.PARTY_AUTHENTICATED_SELECT
    )
    assert "user_id" not in anon.group(1) and "user_id" not in auth.group(1)


def test_expected_privilege_matrix_encodes_the_decisions() -> None:
    expected = package.expected_privileges()
    baseline = package.baseline_privileges()
    assert len(expected) == 312
    for (table, column, role), privilege in expected.items():
        if role == "service_role":
            assert privilege == baseline[(table, column, role)], (table, column)
        if role == "anon":
            assert not privilege["column_insert"] and not privilege["column_update"]
            if table == "marketplace_party":
                assert privilege["column_select"] == (
                    column in package.PARTY_ANON_SELECT
                )
            elif table == "review":
                assert privilege["column_select"] == (
                    column in package.PHASE32C_REVIEW_ANON_COLUMNS
                )
            else:
                assert (
                    privilege["column_select"]
                    == baseline[(table, column, role)]["column_select"]
                )
        if role == "authenticated":
            assert not privilege["table_insert"] and not privilege["table_update"]
            if table == "marketplace_party":
                assert privilege["column_select"] == (column != "user_id")
            else:
                assert privilege["column_insert"] == (
                    column in package.INSERT_ALLOWLIST.get(table, ())
                )
                assert privilege["column_update"] == (
                    column in package.UPDATE_ALLOWLIST.get(table, ())
                )
    assert not expected[("marketplace_party", "user_id", "authenticated")][
        "column_select"
    ]
    assert not expected[("service_request", "lifecycle_state", "authenticated")][
        "column_update"
    ]
    assert not expected[("purchase_order", "lifecycle_state", "authenticated")][
        "column_update"
    ]
    assert baseline[("service_request", "lifecycle_state", "authenticated")][
        "column_update"
    ]
    assert baseline[("purchase_order", "lifecycle_state", "authenticated")][
        "column_update"
    ]


# --------------------------------------------------------------------------
# Policies
# --------------------------------------------------------------------------


def test_new_policy_set_matches_generator_and_postflight_inventory() -> None:
    bodies = policy_bodies(normalized(CORE_PATH))
    assert set(bodies) == {policy for _t, policy, *_ in package.NEW_POLICIES}
    assert len(bodies) == 29
    for table, policy, cmd, mode, role in package.NEW_POLICIES:
        body = bodies[policy]
        assert f"on public.{table} for {cmd.lower()} to {role}" in body, policy
        assert mode == "PERMISSIVE"
        assert "as restrictive" not in body
        assert "or true" not in body
        assert " or " not in body or policy in {
            "phase32d_review_insert_verified",
            "phase32d_service_request_insert_own",
        }, policy
        assert (
            "current_customer_profile_id()" in body
            or "current_marketplace_party_id()" in body
            or "originating_user_id = auth.uid()" in body
        ), policy
    inventory = package.expected_policy_inventory()
    assert len(inventory) == 54
    names = Counter((table, policy) for table, policy, *_ in inventory)
    assert all(count == 1 for count in names.values())
    for table, policy, cmd, mode, role in package.NEW_POLICIES:
        assert (table, policy, cmd, mode, role) in inventory
    for table, dropped in package.DROPPED_POLICIES.items():
        for policy in dropped:
            assert (table, policy) not in names
    assert ("review", "review_select_public") not in names
    assert ("party_capability", "party_capability_select") not in names
    assert (
        "marketplace_party",
        "marketplace_party_select_public",
        "SELECT",
        "PERMISSIVE",
        "anon,authenticated",
    ) in inventory


def _count_signature(body: str, needles: dict[str, int]) -> bool:
    return all(body.count(needle) == count for needle, count in needles.items())


def test_critical_predicates_reject_removal_and_broadening() -> None:
    bodies = policy_bodies(normalized(CORE_PATH))
    owner = "customer_profile_id = public.current_customer_profile_id()"
    party = "marketplace_party_id = public.current_marketplace_party_id()"
    signatures: dict[str, dict[str, int]] = {
        "phase32d_service_request_insert_own": {
            owner: 3,
            "lifecycle_state = 'pending'::public.service_request_state": 1,
            "marketplace_party_id is null": 1,
            "request_address.id = service_request.address_id": 1,
            "related_order_id is null": 1,
            " and ": 6,
            " or ": 1,
        },
        "phase32d_service_request_update_own_pending": {
            owner: 3,
            "lifecycle_state = 'pending'::public.service_request_state": 2,
            "marketplace_party_id is null": 1,
            "request_address.id = service_request.address_id": 1,
            " and ": 5,
        },
        "phase32d_review_insert_verified": {
            owner: 5,
            "public.current_customer_profile_id()": 5,
            "'delivered'::public.order_state": 2,
            "'completed'::public.service_request_state": 2,
            "purchased_line.product_id = review.target_product_id": 1,
            " or ": 3,
        },
        "phase32d_address_delete_own": {
            owner: 1,
            "referencing_request.address_id = address.id": 1,
            "referencing_service.address_id = address.id": 1,
            "referencing_order.address_id = address.id": 1,
            "not exists": 3,
        },
        "phase32d_cart_line_insert_own": {
            "owned_cart.customer_profile_id = public.current_customer_profile_id()": 1,
            "'published'::public.product_state": 1,
            "'approved'::public.party_approval_state": 1,
            "product_category.is_active": 1,
            "chosen_color.stock_quantity > 0": 1,
        },
        "phase32d_custom_offering_insert_own": {
            party: 1,
            "public.current_party_is_approved()": 1,
            "offered_design.originating_user_id = auth.uid()": 1,
        },
        "phase32d_custom_offering_delete_own": {
            party: 1,
            "public.current_party_is_approved()": 1,
            "referencing_order.custom_offering_id = custom_offering.id": 1,
        },
        "phase32d_party_capability_insert_own": {
            party: 1,
            "public.current_party_is_approved()": 1,
            "declared_service.is_active": 1,
        },
        "phase32d_offer_line_item_update_own": {
            "parent_offer.marketplace_party_id = "
            "public.current_marketplace_party_id()": 2,
            "'submitted'::public.offer_state": 2,
        },
        "phase32d_furnishing_request_design_version_delete_own": {
            "parent_request.customer_profile_id = "
            "public.current_customer_profile_id()": 1,
            "'draft'::public.furnishing_request_state": 1,
            "'open'::public.furnishing_request_state": 1,
        },
    }
    terminal = (
        "'accepted'::public.furnishing_request_state",
        "'withdrawn'",
        "'closed'",
    )

    def is_narrow(name: str, candidate: str) -> bool:
        return (
            _count_signature(candidate, signatures[name])
            and candidate.count(" or ") == signatures[name].get(" or ", 0)
            and "or true" not in candidate
            and "or 1 = 1" not in candidate
            and not any(state in candidate for state in terminal)
        )

    for name, needles in signatures.items():
        body = bodies[name]
        assert is_narrow(name, body), name
        for needle, count in needles.items():
            for occurrence in range(count):
                position = -1
                for _ in range(occurrence + 1):
                    position = body.index(needle, position + 1)
                mutated = body[:position] + body[position + len(needle) :]
                assert not is_narrow(name, mutated), (name, needle, occurrence)
        for broadening in (
            body.replace(" and ", " or ", 1),
            body.replace(" );", " or true );", 1),
            body + " or 1 = 1",
        ):
            assert broadening != body
            assert not is_narrow(name, broadening), name
    frdv = bodies["phase32d_furnishing_request_design_version_delete_own"]
    assert not is_narrow(
        "phase32d_furnishing_request_design_version_delete_own",
        frdv.replace(
            "'open'::public.furnishing_request_state",
            "'accepted'::public.furnishing_request_state",
        ),
    )


# --------------------------------------------------------------------------
# Transition functions
# --------------------------------------------------------------------------


def test_transition_functions_are_exact_uniform_and_narrow() -> None:
    sql = normalized(CORE_PATH)
    bodies = function_bodies(sql)
    for name, expected_sets in FUNCTION_SET_LISTS.items():
        function = bodies[name]
        body = function[function.index("as $function$") : function.index("$function$;")]
        assert "returns pg_catalog.bool " in function
        assert (
            "language plpgsql volatile security definer set search_path = ''"
            in function
        )
        assert "auth.uid()" in body
        assert "get diagnostics affected_rows = row_count" in body
        assert "return affected_rows = 1" in body
        assert "or true" not in body
        assert re.findall(r"\bset\s+([a-z_]+)\s*=", body) == [expected_sets[0]]
        assignment = body.split("set lifecycle_state", 1)[1].split("where", 1)[0]
        assigned = ["lifecycle_state"] + re.findall(r",\s*([a-z_]+)\s*=", assignment)
        assert assigned == expected_sets, name
        assert "pg_catalog.now()" in body or "_at" not in "".join(expected_sets[1:])
        relation = "service_request" if "service" in name else "purchase_order"
        assert f'update "public".{relation} as' in body
        grants = sql[sql.index(f"alter function public.{name}(") :]
        grants = grants[: grants.index("to authenticated, service_role;") + 31]
        assert "owner to postgres" in grants
        assert "from public, anon, authenticated, service_role" in grants
    for name, (old, new, forbidden) in FUNCTION_DIRECTIONS.items():
        body = bodies[name]
        assert f"lifecycle_state::text = '{old}'" in body, name
        assert f"set lifecycle_state = '{new}'" in body, name
        for state in forbidden:
            assert f"'{state}'" not in body, (name, state)
    advance = bodies["advance_purchase_order"]
    assert "set lifecycle_state = next_state" in advance
    for pair in (
        "('pending', 'confirmed')",
        "('confirmed', 'preparing')",
        "('preparing', 'out_for_delivery')",
        "('out_for_delivery', 'delivered')",
    ):
        assert pair in advance
    assert "'cancelled'" not in advance
    assert "party.approval_state::text = 'approved'" in advance
    accept = bodies["accept_service_request"]
    assert "agreed_price is null or agreed_price < 0" in accept
    assert "capability.service_type_id = request_row.service_type_id" in accept
    assert "request_row.marketplace_party_id is null" in accept
    for customer_function in ("cancel_service_request", "cancel_purchase_order"):
        assert "customer.user_id = auth.uid()" in bodies[customer_function]
        assert "marketplace_party" not in bodies[customer_function]
    for seller_function in ("start_service_request", "complete_service_request"):
        assert "party.id = request_row.marketplace_party_id" in bodies[seller_function]
        assert "customer_profile" not in bodies[seller_function]


def test_postflight_checks_inventory_privileges_predicates_and_functions() -> None:
    sql = read(CORE_PATH)
    postflight = sql[sql.index("DO $phase32d_postflight$") :]
    assert package.policy_inventory_values() in postflight
    assert package.privilege_values(package.expected_privileges()) in postflight
    assert "<> 8 THEN" in postflight
    assert "acl.is_grantable OR acl.grantee = 0" in postflight
    for message in (
        "postflight policy inventory mismatch",
        "postflight policy anchor mismatch",
        "postflight predicate mismatch",
        "postflight privilege mismatch",
        "postflight transition function mismatch",
        "postflight RLS/FORCE mismatch",
    ):
        assert message in postflight
    for signature in package.TRANSITION_FUNCTIONS:
        assert f"'public.{signature}'::text" in postflight
    assert "NOT LIKE '%or true%'" in postflight or "LIKE '%or true%'" in postflight


# --------------------------------------------------------------------------
# Verifier
# --------------------------------------------------------------------------


def test_verifier_is_twelve_select_only_sections_with_uniform_shape() -> None:
    verify = read(VERIFY_PATH)
    statements = parse_sql(verify)
    assert len(statements) == 12
    assert all(isinstance(raw.stmt, ast.SelectStmt) for raw in statements)
    assert len(re.findall(r"(?m)^-- (?:0[1-9]|1[0-2])\.", verify)) == 12
    lowered = verify.lower()
    assert lowered.count("as check_name") == 12
    assert lowered.count("as expected_count") == 12
    assert lowered.count("as actual_count") == 12
    assert lowered.count("as failed_count") == 12
    assert lowered.count("as check_passed") == 12
    assert package.inventory_values() in verify
    assert package.privilege_values(package.expected_privileges()) in verify
    assert package.policy_inventory_values() in verify
    for name in (
        "phase32c_prerequisites_and_no_survivors",
        "for_all_policies_exact",
        "touched_table_exact_inventory",
        "touched_table_exact_privileges",
        "touched_table_policy_inventory",
        "new_policies_owner_anchored",
        "new_policy_required_predicates",
        "transition_function_definitions",
        "transition_function_grants",
        "helper_functions_unchanged",
        "rls_enabled_unforced_everywhere",
        "storage_and_default_acls_reported",
    ):
        assert f"'{name}'::text AS check_name" in verify


# --------------------------------------------------------------------------
# Document and ledger reconciliation
# --------------------------------------------------------------------------


def _ledger_policies(doc: str) -> list[tuple[str, str, str, str]]:
    pattern = re.compile(
        r"^\| ([a-z0-9_]+) \| ([a-z0-9_]+) \| (?:PERMISSIVE|RESTRICTIVE) \| "
        r"\{[a-z_,]+\} \| ([a-z_]+) \| ([^|]+) \|$",
        re.MULTILINE,
    )
    return [(t, p, c, b.strip()) for t, p, c, b in pattern.findall(doc)]


def _ledger_findings(doc: str) -> list[tuple[str, str, str, str, str, str, str]]:
    pattern = re.compile(
        r"^\| (phase32[cd]_\d{4}) \| ([a-z]+) \| ([a-z0-9_]+) \| ([^|]+) \| "
        r"([a-z0-9_]+) \| ([a-z_]+) \| ([^|]+) \|$",
        re.MULTILINE,
    )
    return [
        (i, s, t, p.strip(), f, c, b.strip())
        for i, s, t, p, f, c, b in pattern.findall(doc)
    ]


def test_ledgers_reconcile_bidirectionally_with_phase32c_deferred_items() -> None:
    doc = read(DOC_PATH)
    prior = read(LEDGER_32C_PATH)
    deferred_policies = {
        (t, p)
        for t, p, c, _b in _ledger_policies(prior)
        if c == "deferred_with_named_blocker"
    }
    deferred_findings = {
        row[0]: row
        for row in _ledger_findings(prior)
        if row[5] == "deferred_with_named_blocker"
    }
    assert len(deferred_policies) == 10
    assert len(deferred_findings) == 46

    policies = _ledger_policies(doc)
    assert {(t, p) for t, p, _c, _b in policies} == deferred_policies
    assert len(policies) == 10
    assert all(c == "remediated" for _t, _p, c, _b in policies)
    assert all(b == f"phase32d_operation_split:{t}.{p}" for t, p, _c, b in policies)

    findings = _ledger_findings(doc)
    ids = [row[0] for row in findings]
    assert len(ids) == len(set(ids)) == 48
    assert set(ids) == set(deferred_findings) | {"phase32d_0001", "phase32d_0002"}
    for row in findings:
        finding_id, severity, table, policy, finding, classification, basis = row
        assert classification in {
            "remediated",
            "accepted_with_evidence",
            "audit_false_positive",
        }, finding_id
        assert basis, finding_id
        if finding_id in deferred_findings:
            prior_row = deferred_findings[finding_id]
            assert (severity, table, policy, finding) == prior_row[1:5], finding_id
    classifications = Counter(row[5] for row in findings)
    classifications["remediated"] += 10
    assert classifications == {
        "remediated": 20,
        "accepted_with_evidence": 31,
        "audit_false_positive": 7,
    }
    by_id = {row[0]: row[5] for row in findings}
    assert by_id["phase32c_0055"] == "remediated"
    assert by_id["phase32c_0036"] == "audit_false_positive"
    assert by_id["phase32c_0047"] == "audit_false_positive"
    assert by_id["phase32c_0025"] == "accepted_with_evidence"
    assert by_id["phase32c_0030"] == "accepted_with_evidence"
    for finding_id in (
        "phase32c_0021",
        "phase32c_0022",
        "phase32c_0023",
        "phase32c_0024",
        "phase32c_0035",
    ):
        assert by_id[finding_id] == "audit_false_positive"
    for finding_id in (
        "phase32c_0057",
        "phase32c_0067",
        "phase32c_0074",
        "phase32c_0077",
        "phase32c_0082",
        "phase32c_0086",
        "phase32c_0116",
    ):
        assert by_id[finding_id] == "remediated"
    assert by_id["phase32d_0001"] == by_id["phase32d_0002"] == "remediated"


def test_document_records_design_allowlists_transitions_and_review_gate() -> None:
    doc = read(DOC_PATH)
    assert doc.count(STATUS) == 2
    assert "byte-identical to that generator" in doc
    assert "## Touched tables and the exact changes" in doc
    for table in package.TOUCHED_TABLES:
        assert f"| {table} |" in doc
    for table, allowed in package.INSERT_ALLOWLIST.items():
        assert ", ".join(allowed) in doc, table
    for table, allowed in package.UPDATE_ALLOWLIST.items():
        assert ", ".join(allowed) in doc, table
    for name in FUNCTION_SET_LISTS:
        assert f"`{name}(" in doc
    assert "pending → confirmed → preparing → out_for_delivery → delivered" in doc
    assert "accepted → in_progress" in doc
    assert "No client role can read `user_id`" in doc
    assert "## Live acceptance contract" in doc
    assert "scripts/live_phase_3_2d_acceptance.py" in doc
    assert "never inserts, deletes, changes a lifecycle state" in doc
    assert "- `deferred_with_named_blocker`: 0" in doc
    assert "104-column" in doc
    assert "312-row" in doc
    assert "12 SELECT-only sections" in doc
