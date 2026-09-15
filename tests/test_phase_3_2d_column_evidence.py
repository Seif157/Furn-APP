"""Static tests binding the Phase 3.2D column, privilege, enum, and constraint
evidence to the claims made in the scoping document."""

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT_ROOT / "docs" / "evidence" / "phase-3.2d"
SCOPING_PATH = PROJECT_ROOT / "docs" / "phase-3.2d-scoping.md"
DECISIONS_PATH = PROJECT_ROOT / "docs" / "phase-3.2d-decisions.md"

INVENTORY_HEADERS = (
    "table_name",
    "ordinal_position",
    "column_name",
    "formatted_type",
    "type_name",
    "type_modifier",
    "is_not_null",
    "default_expression",
    "identity_kind",
    "generated_kind",
)
PRIVILEGE_HEADERS = (
    "table_name",
    "ordinal_position",
    "column_name",
    "role_name",
    "table_select",
    "table_insert",
    "table_update",
    "table_delete",
    "column_select",
    "column_insert",
    "column_update",
    "has_column_acl",
)
ENUM_HEADERS = ("enum_type_name", "label_order", "label", "used_by_columns")
CONSTRAINT_HEADERS = (
    "table_name",
    "constraint_name",
    "constraint_kind",
    "definition",
    "referenced_table",
    "on_delete",
)
STATE_COLUMN_PATTERN = re.compile(
    r"(approval_state|confirmation_state|lifecycle_state|publication_state|status|state_reason)"
)
NO_STATE_TABLES = (
    "customer_profile",
    "design",
    "design_version",
    "design_product_reference",
    "party_capability",
)


def csv_rows(name: str, headers: tuple[str, ...]) -> list[dict[str, str]]:
    path = EVIDENCE / name
    assert path.is_file(), f"missing evidence: {path}"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == headers
        rows = list(reader)
    assert all(None not in row for row in rows)
    return rows


def inventory() -> list[dict[str, str]]:
    return csv_rows("column-inventory.csv", INVENTORY_HEADERS)


def privileges() -> list[dict[str, str]]:
    rows = csv_rows("column-privileges.csv", PRIVILEGE_HEADERS)
    for row in rows:
        assert row["role_name"] in {"anon", "authenticated", "service_role"}
        for flag in PRIVILEGE_HEADERS[4:]:
            assert row[flag] in {"true", "false"}, (row["table_name"], flag)
    return rows


def enums() -> dict[str, list[str]]:
    labels: dict[str, list[str]] = defaultdict(list)
    for row in csv_rows("state-enums.csv", ENUM_HEADERS):
        labels[row["enum_type_name"]].append(row["label"])
    return dict(labels)


def constraints() -> list[dict[str, str]]:
    rows = csv_rows("constraints.csv", CONSTRAINT_HEADERS)
    assert all(row["constraint_kind"] in {"p", "u", "f", "c"} for row in rows)
    return rows


def columns_by_table(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        result[row["table_name"]].append(row["column_name"])
    return dict(result)


def test_inventory_export_is_complete_against_privilege_export() -> None:
    inventory_columns = {(row["table_name"], row["column_name"]) for row in inventory()}
    privilege_columns = {
        (row["table_name"], row["column_name"]) for row in privileges()
    }
    missing = sorted(privilege_columns - inventory_columns)
    assert not missing, (
        "column-inventory.csv is incomplete (the SQL editor caps results at "
        "100 rows; use Download CSV). Missing: "
        + ", ".join(f"{table}.{column}" for table, column in missing)
    )
    assert not (inventory_columns - privilege_columns)


def test_inventory_export_shape_and_counts() -> None:
    rows = inventory()
    assert len(rows) == 149
    tables = columns_by_table(rows)
    assert len(tables) == 18
    for table, columns in tables.items():
        ordinals = [
            int(row["ordinal_position"]) for row in rows if row["table_name"] == table
        ]
        assert ordinals == list(range(1, len(columns) + 1)), table
        assert len(set(columns)) == len(columns), table
    assert all(row["identity_kind"] == "" for row in rows)
    generated = [
        (row["table_name"], row["column_name"]) for row in rows if row["generated_kind"]
    ]
    assert generated == [
        ("offer_line_item", "line_total"),
        ("order_line_item", "line_total"),
    ]
    doc = read_scoping()
    assert "| 149 columns over 18 tables |" in doc


def test_no_state_columns_on_pack_b_tables() -> None:
    tables = columns_by_table(inventory())
    for table in NO_STATE_TABLES:
        assert table in tables, table
        assert not any(
            STATE_COLUMN_PATTERN.search(column) for column in tables[table]
        ), table
    assert tables["design_product_reference"] == ["design_id", "product_id"]
    assert tables["party_capability"] == [
        "marketplace_party_id",
        "service_type_id",
        "declared_at",
    ]
    doc = read_scoping()
    assert doc.count("| audit_false_positive |") == 5
    assert "No state columns exist" in doc


def test_service_request_and_purchase_order_inventories_match_document() -> None:
    tables = columns_by_table(inventory())
    assert tables["service_request"] == [
        "id",
        "customer_profile_id",
        "service_type_id",
        "marketplace_party_id",
        "address_id",
        "related_order_id",
        "scheduled_date",
        "scheduled_time",
        "details",
        "price",
        "lifecycle_state",
        "accepted_at",
        "completed_at",
        "created_at",
    ]
    assert len(tables["purchase_order"]) == 24
    assert tables["purchase_order"][:5] == [
        "id",
        "customer_profile_id",
        "marketplace_party_id",
        "address_id",
        "origin",
    ]
    defaults = {
        (row["table_name"], row["column_name"]): row["default_expression"]
        for row in inventory()
    }
    assert (
        defaults[("service_request", "lifecycle_state")]
        == "'pending'::service_request_state"
    )
    assert defaults[("purchase_order", "lifecycle_state")] == "'pending'::order_state"
    assert defaults[("service_request", "created_at")] == "now()"
    assert defaults[("purchase_order", "placed_at")] == "now()"


def test_privilege_export_shape_and_documented_surfaces() -> None:
    rows = privileges()
    assert len(rows) == 447
    tables = {row["table_name"] for row in rows}
    assert len(tables) == 18
    per_table_role = Counter((row["table_name"], row["role_name"]) for row in rows)
    for table in tables:
        counts = {
            per_table_role[(table, role)]
            for role in ("anon", "authenticated", "service_role")
        }
        assert len(counts) == 1, table

    def updatable(table: str, role: str) -> list[str]:
        return [
            row["column_name"]
            for row in rows
            if row["table_name"] == table
            and row["role_name"] == role
            and row["column_update"] == "true"
        ]

    def table_privilege(table: str, role: str, flag: str) -> bool:
        values = {
            row[flag]
            for row in rows
            if row["table_name"] == table and row["role_name"] == role
        }
        assert len(values) == 1
        return values.pop() == "true"

    assert updatable("service_request", "authenticated") == [
        "scheduled_date",
        "scheduled_time",
        "details",
        "lifecycle_state",
        "completed_at",
    ]
    assert not table_privilege("service_request", "authenticated", "table_update")
    assert table_privilege("service_request", "authenticated", "table_insert")
    assert updatable("purchase_order", "authenticated") == ["lifecycle_state", "notes"]
    assert not table_privilege("purchase_order", "authenticated", "table_update")
    assert table_privilege("purchase_order", "authenticated", "table_insert")
    assert table_privilege("marketplace_party", "anon", "table_select")
    assert table_privilege("marketplace_party", "authenticated", "table_select")
    assert updatable("marketplace_party", "authenticated") == [
        "business_name",
        "business_description",
        "logo_url",
        "coverage_area",
    ]
    for table in NO_STATE_TABLES:
        assert not table_privilege(table, "anon", "table_insert")
        assert not table_privilege(table, "anon", "table_update")
    for table in tables:
        assert table_privilege(table, "service_role", "table_select")
        assert table_privilege(table, "service_role", "table_insert")
        assert table_privilege(table, "service_role", "table_update")
        assert not table_privilege(table, "anon", "table_insert")
        assert not table_privilege(table, "anon", "table_update")
    doc = read_scoping()
    assert "| 447 rows: 18 tables, 3 roles |" in doc


def test_enum_export_matches_documented_state_machines() -> None:
    labels = enums()
    assert sum(len(values) for values in labels.values()) == 41
    assert len(labels) == 11
    assert labels["service_request_state"] == [
        "pending",
        "accepted",
        "in_progress",
        "completed",
        "cancelled",
    ]
    assert labels["order_state"] == [
        "pending",
        "confirmed",
        "preparing",
        "out_for_delivery",
        "delivered",
        "cancelled",
    ]
    assert labels["furnishing_request_state"] == [
        "draft",
        "open",
        "accepted",
        "withdrawn",
        "closed",
    ]
    assert labels["review_target_kind"] == [
        "product",
        "service_request",
        "marketplace_party",
    ]
    assert labels["party_approval_state"] == [
        "pending",
        "approved",
        "rejected",
        "suspended",
    ]
    doc = read_scoping()
    assert "`pending`, `accepted`, `in_progress`, `completed`, `cancelled`" in doc
    order_states = "`pending`, `confirmed`, `preparing`, `out_for_delivery`, "
    assert order_states + "`delivered`, `cancelled`" in doc
    assert "| 41 labels over 11 enums |" in doc
    decisions = DECISIONS_PATH.read_text(encoding="utf-8")
    assert "accepted->in_progress, in_progress->completed" in decisions
    assert "pending->confirmed->preparing->out_for_delivery->delivered" in decisions


def test_constraint_export_backs_documented_structural_claims() -> None:
    rows = constraints()
    assert len(rows) == 103
    assert len({row["table_name"] for row in rows}) == 18
    by_name = {row["constraint_name"]: row for row in rows}
    assert (
        by_name["cart_customer_unique"]["definition"] == "UNIQUE (customer_profile_id)"
    )
    assert by_name["customer_profile_user_unique"]["definition"] == "UNIQUE (user_id)"
    assert (
        by_name["cart_line_unique_per_color"]["definition"]
        == "UNIQUE (cart_id, product_color_id)"
    )
    assert by_name["review_exactly_one_target"]["constraint_kind"] == "c"
    assert (
        by_name["design_product_reference_pk"]["definition"]
        == "PRIMARY KEY (design_id, product_id)"
    )
    assert by_name["furnishing_request_design_version_pk"]["definition"] == (
        "PRIMARY KEY (furnishing_request_id, design_version_id)"
    )
    assert by_name["party_capability_pk"]["definition"] == (
        "PRIMARY KEY (marketplace_party_id, service_type_id)"
    )
    for name in (
        "purchase_order_address_fk",
        "service_request_address_fk",
        "purchase_order_custom_offering_fk",
    ):
        assert by_name[name]["on_delete"] == "restrict", name
    assert (
        "'completed'::service_request_state OR completed_at IS NOT NULL"
        in (by_name["service_request_completed_timestamp"]["definition"])
    )
    assert (
        "cancelled_at IS NOT NULL"
        in by_name["purchase_order_cancelled_timestamp"]["definition"]
    )
    doc = read_scoping()
    assert "| 103 constraints over 18 tables |" in doc
    assert "`customer_profile_user_unique (user_id)`" in doc
    assert "`cart_customer_unique (customer_profile_id)`" in doc


def read_scoping() -> str:
    return SCOPING_PATH.read_text(encoding="utf-8")
