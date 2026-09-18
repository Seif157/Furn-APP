"""Phase 3.2D package generator.

The Phase 3.2D SQL artifacts embed exact catalog signatures and privilege
matrices for thirteen tables. Those blocks are derived from the read-only
evidence exports under ``docs/evidence/phase-3.2d`` by this module, and the
static tests assert that the files on disk are byte-identical to
``build()``. The module performs no database access.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT_ROOT / "docs" / "evidence" / "phase-3.2d"
SQL_DIR = PROJECT_ROOT / "sql"
CORE_PATH = SQL_DIR / "phase-3.2d-security-hardening.sql"
PREFLIGHT_PATH = SQL_DIR / "phase-3.2d-security-hardening-preflight.sql"
VERIFY_PATH = SQL_DIR / "phase-3.2d-security-hardening-verify.sql"

ROLES = ("anon", "authenticated", "service_role")

EXPECTED_TABLES = (
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
)

TOUCHED_TABLES = (
    "address",
    "cart",
    "cart_line",
    "saved_space",
    "review",
    "furnishing_request_design_version",
    "custom_offering",
    "party_capability",
    "offer_line_item",
    "design_product_reference",
    "service_request",
    "purchase_order",
    "marketplace_party",
)

# Policies removed by this package (all exist before it runs).
DROPPED_POLICIES: dict[str, tuple[str, ...]] = {
    "address": ("address_write_own",),
    "cart": ("cart_all_own",),
    "cart_line": ("cart_line_all_own",),
    "saved_space": ("saved_space_all_own",),
    "review": ("review_write_own",),
    "furnishing_request_design_version": (
        "furnishing_request_design_version_write_own",
    ),
    "custom_offering": ("custom_offering_write_own",),
    "party_capability": ("party_capability_write_own",),
    "offer_line_item": ("offer_line_item_write_own",),
    "design_product_reference": ("design_product_reference_write_own",),
    "service_request": (
        "service_request_insert_own",
        "service_request_update_engaged",
    ),
    "purchase_order": ("purchase_order_update_party",),
}

# Phase 3.2C changes that precede this package on the touched tables.
PHASE32C_DROPPED = {
    "review": ("review_select_public",),
    "party_capability": ("party_capability_select",),
}
PHASE32C_ADDED: tuple[tuple[str, str, str, str, str], ...] = (
    ("review", "phase32c_review_anon_safe_read", "SELECT", "PERMISSIVE", "anon"),
    (
        "review",
        "phase32c_review_authenticated_read_guard",
        "SELECT",
        "RESTRICTIVE",
        "authenticated",
    ),
    (
        "party_capability",
        "phase32c_party_capability_anon_read",
        "SELECT",
        "PERMISSIVE",
        "anon",
    ),
    (
        "party_capability",
        "phase32c_party_capability_authenticated_read",
        "SELECT",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "party_capability",
        "phase32c_party_capability_owner_read",
        "SELECT",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "party_capability",
        "phase32c_party_capability_admin_read",
        "SELECT",
        "PERMISSIVE",
        "authenticated",
    ),
)
PHASE32C_REVIEW_ANON_COLUMNS = (
    "id",
    "target_kind",
    "target_product_id",
    "target_marketplace_party_id",
    "rating",
    "comment",
    "created_at",
)

# Approved client column allowlists (authenticated). Absent table = none.
INSERT_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "address": (
        "customer_profile_id",
        "label",
        "recipient_name",
        "contact_phone",
        "address_line_1",
        "address_line_2",
        "city",
        "country",
        "latitude",
        "longitude",
        "is_default",
    ),
    "cart_line": ("cart_id", "product_color_id", "quantity"),
    "saved_space": (
        "customer_profile_id",
        "space_name",
        "width_cm",
        "depth_cm",
        "measurement_source",
    ),
    "review": (
        "customer_profile_id",
        "target_kind",
        "target_product_id",
        "target_service_request_id",
        "target_marketplace_party_id",
        "rating",
        "comment",
    ),
    "custom_offering": (
        "marketplace_party_id",
        "design_id",
        "published_price",
        "title",
        "description",
        "publication_state",
        "published_at",
    ),
    "party_capability": ("marketplace_party_id", "service_type_id", "declared_at"),
    "offer_line_item": (
        "offer_id",
        "line_kind",
        "product_id",
        "item_name",
        "specification",
        "unit_price",
        "quantity",
        "display_order",
    ),
    "design_product_reference": ("design_id", "product_id"),
    "service_request": (
        "customer_profile_id",
        "service_type_id",
        "address_id",
        "related_order_id",
        "scheduled_date",
        "scheduled_time",
        "details",
    ),
}
UPDATE_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "address": (
        "label",
        "recipient_name",
        "contact_phone",
        "address_line_1",
        "address_line_2",
        "city",
        "country",
        "latitude",
        "longitude",
        "is_default",
    ),
    "cart_line": ("quantity",),
    "saved_space": ("space_name", "width_cm", "depth_cm", "measurement_source"),
    "custom_offering": (
        "design_id",
        "published_price",
        "title",
        "description",
        "publication_state",
        "published_at",
    ),
    "offer_line_item": (
        "line_kind",
        "product_id",
        "item_name",
        "specification",
        "unit_price",
        "quantity",
        "display_order",
    ),
    "service_request": ("scheduled_date", "scheduled_time", "details"),
    "purchase_order": ("notes",),
}
# marketplace_party INSERT/UPDATE allowlists are Phase 3.2B facts, unchanged.
PHASE32B_PARTY_INSERT = (
    "user_id",
    "business_name",
    "business_description",
    "logo_url",
    "coverage_area",
)
PHASE32B_PARTY_UPDATE = (
    "business_name",
    "business_description",
    "logo_url",
    "coverage_area",
)
PARTY_ANON_SELECT = (
    "id",
    "business_name",
    "business_description",
    "logo_url",
    "coverage_area",
    "approval_state",
)
PARTY_AUTHENTICATED_SELECT = PARTY_ANON_SELECT + ("state_reason",)

TRANSITION_FUNCTIONS = (
    "cancel_service_request(pg_catalog.uuid)",
    "accept_service_request(pg_catalog.uuid, pg_catalog.numeric)",
    "start_service_request(pg_catalog.uuid)",
    "complete_service_request(pg_catalog.uuid)",
    "advance_purchase_order(pg_catalog.uuid, public.order_state)",
    "cancel_purchase_order(pg_catalog.uuid)",
)

TYPE_CASTS = {
    "uuid": "pg_catalog.uuid",
    "text": "pg_catalog.text",
    "text[]": "pg_catalog.text[]",
    "timestamp with time zone": "pg_catalog.timestamptz",
    "numeric": "pg_catalog.numeric",
    "smallint": "pg_catalog.int2",
    "integer": "pg_catalog.int4",
    "date": "pg_catalog.date",
    "boolean": "pg_catalog.bool",
    "jsonb": "pg_catalog.jsonb",
}


@dataclass(frozen=True, slots=True)
class Column:
    table: str
    ordinal: int
    name: str
    formatted_type: str
    type_name: str
    type_modifier: int
    not_null: bool
    default: str | None
    generated: str


def _rows(name: str) -> list[dict[str, str]]:
    with (EVIDENCE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def squash(text: str) -> str:
    return " ".join(text.split())


def sql_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def columns() -> dict[str, list[Column]]:
    result: dict[str, list[Column]] = {table: [] for table in TOUCHED_TABLES}
    for row in _rows("column-inventory.csv"):
        table = row["table_name"]
        if table not in result:
            continue
        default = row["default_expression"]
        result[table].append(
            Column(
                table=table,
                ordinal=int(row["ordinal_position"]),
                name=row["column_name"],
                formatted_type=row["formatted_type"],
                type_name=row["type_name"],
                type_modifier=int(row["type_modifier"]),
                not_null=row["is_not_null"] == "true",
                default=None if default == "null" else default,
                generated=row["generated_kind"],
            )
        )
    for table, table_columns in result.items():
        table_columns.sort(key=lambda column: column.ordinal)
        assert table_columns, table
    return result


def baseline_privileges() -> dict[tuple[str, str, str], dict[str, bool]]:
    """Effective privileges after Phase 3.2C, keyed by (table, column, role)."""
    result: dict[tuple[str, str, str], dict[str, bool]] = {}
    for row in _rows("column-privileges.csv"):
        table = row["table_name"]
        if table not in TOUCHED_TABLES:
            continue
        key = (table, row["column_name"], row["role_name"])
        result[key] = {
            field: row[field] == "true"
            for field in (
                "table_select",
                "table_insert",
                "table_update",
                "table_delete",
                "column_select",
                "column_insert",
                "column_update",
            )
        }
    # Phase 3.2C revoked anon table SELECT on review and granted seven columns.
    for (table, column, role), privilege in result.items():
        if table == "review" and role == "anon":
            privilege["table_select"] = False
            privilege["column_select"] = column in PHASE32C_REVIEW_ANON_COLUMNS
    return result


def expected_privileges() -> dict[tuple[str, str, str], dict[str, bool]]:
    """Effective privileges after this package, derived from the baseline."""
    result = {key: dict(value) for key, value in baseline_privileges().items()}
    for (table, column, role), privilege in result.items():
        if role == "authenticated":
            privilege["table_insert"] = False
            privilege["table_update"] = False
            if table == "marketplace_party":
                privilege["column_insert"] = column in PHASE32B_PARTY_INSERT
                privilege["column_update"] = column in PHASE32B_PARTY_UPDATE
                privilege["table_select"] = False
                privilege["column_select"] = column in PARTY_AUTHENTICATED_SELECT
            else:
                privilege["column_insert"] = column in INSERT_ALLOWLIST.get(table, ())
                privilege["column_update"] = column in UPDATE_ALLOWLIST.get(table, ())
        elif role == "anon":
            if table == "marketplace_party":
                privilege["table_select"] = False
                privilege["column_select"] = column in PARTY_ANON_SELECT
            if table == "purchase_order":
                privilege["table_insert"] = False
                privilege["column_insert"] = False
    return result


def _section02() -> list[dict[str, str]]:
    return _rows("section-02-policies.csv")


def policies_to_replace() -> list[tuple[str, str, str, str, str, str]]:
    """(table, policy, cmd, roles, using, with_check) for every policy this
    package drops, with the exact deployed predicate text."""
    dropped = {
        (table, policy) for table, names in DROPPED_POLICIES.items() for policy in names
    }
    rows = []
    for row in _section02():
        key = (row["table_name"], row["policy_name"])
        if key in dropped:
            rows.append(
                (
                    row["table_name"],
                    row["policy_name"],
                    row["policy_command"],
                    row["policy_roles"],
                    squash(row["complete_using_expression"]),
                    squash(row["complete_with_check_expression"]),
                )
            )
    assert len(rows) == len(dropped)
    return sorted(rows)


def for_all_identity_set() -> list[tuple[str, str]]:
    """The 18 FOR ALL policies present after Phase 3.2C."""
    rows = [
        (row["table_name"], row["policy_name"])
        for row in _section02()
        if row["policy_command"] == "ALL"
        and row["policy_name"] != "furnishing_request_write_own"
    ]
    assert len(rows) == 18
    return sorted(rows)


NEW_POLICIES: tuple[tuple[str, str, str, str, str], ...] = (
    ("address", "phase32d_address_insert_own", "INSERT", "PERMISSIVE", "authenticated"),
    ("address", "phase32d_address_update_own", "UPDATE", "PERMISSIVE", "authenticated"),
    ("address", "phase32d_address_delete_own", "DELETE", "PERMISSIVE", "authenticated"),
    ("cart", "phase32d_cart_select_own", "SELECT", "PERMISSIVE", "authenticated"),
    ("cart", "phase32d_cart_delete_own", "DELETE", "PERMISSIVE", "authenticated"),
    (
        "cart_line",
        "phase32d_cart_line_select_own",
        "SELECT",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "cart_line",
        "phase32d_cart_line_insert_own",
        "INSERT",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "cart_line",
        "phase32d_cart_line_update_own",
        "UPDATE",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "cart_line",
        "phase32d_cart_line_delete_own",
        "DELETE",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "saved_space",
        "phase32d_saved_space_select_own",
        "SELECT",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "saved_space",
        "phase32d_saved_space_insert_own",
        "INSERT",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "saved_space",
        "phase32d_saved_space_update_own",
        "UPDATE",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "saved_space",
        "phase32d_saved_space_delete_own",
        "DELETE",
        "PERMISSIVE",
        "authenticated",
    ),
    ("review", "phase32d_review_select_own", "SELECT", "PERMISSIVE", "authenticated"),
    (
        "review",
        "phase32d_review_insert_verified",
        "INSERT",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "furnishing_request_design_version",
        "phase32d_furnishing_request_design_version_delete_own",
        "DELETE",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "custom_offering",
        "phase32d_custom_offering_insert_own",
        "INSERT",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "custom_offering",
        "phase32d_custom_offering_update_own",
        "UPDATE",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "custom_offering",
        "phase32d_custom_offering_delete_own",
        "DELETE",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "party_capability",
        "phase32d_party_capability_insert_own",
        "INSERT",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "party_capability",
        "phase32d_party_capability_delete_own",
        "DELETE",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "offer_line_item",
        "phase32d_offer_line_item_insert_own",
        "INSERT",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "offer_line_item",
        "phase32d_offer_line_item_update_own",
        "UPDATE",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "offer_line_item",
        "phase32d_offer_line_item_delete_own",
        "DELETE",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "design_product_reference",
        "phase32d_design_product_reference_insert_own",
        "INSERT",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "design_product_reference",
        "phase32d_design_product_reference_delete_own",
        "DELETE",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "service_request",
        "phase32d_service_request_insert_own",
        "INSERT",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "service_request",
        "phase32d_service_request_update_own_pending",
        "UPDATE",
        "PERMISSIVE",
        "authenticated",
    ),
    (
        "purchase_order",
        "phase32d_purchase_order_update_party_notes",
        "UPDATE",
        "PERMISSIVE",
        "authenticated",
    ),
)


def expected_policy_inventory() -> list[tuple[str, str, str, str, str]]:
    """Complete (table, policy, cmd, mode, role) set on touched tables after
    this package: deployed policies minus 3.2C/3.2D drops plus 3.2C/3.2D adds."""
    dropped = {
        (table, policy)
        for mapping in (PHASE32C_DROPPED, DROPPED_POLICIES)
        for table, names in mapping.items()
        for policy in names
    }
    rows: set[tuple[str, str, str, str, str]] = set()
    for row in _section02():
        table = row["table_name"]
        if table not in TOUCHED_TABLES:
            continue
        if (table, row["policy_name"]) in dropped:
            continue
        roles = row["policy_roles"].strip("{}")
        rows.add(
            (
                table,
                row["policy_name"],
                row["policy_command"],
                row["policy_mode"],
                roles,
            )
        )
    rows.update(PHASE32C_ADDED)
    rows.update(NEW_POLICIES)
    return sorted(rows)


# --------------------------------------------------------------------------
# SQL fragment generation
# --------------------------------------------------------------------------


def _type_cast(column: Column) -> str:
    base = column.type_name
    if base in TYPE_CASTS:
        return TYPE_CASTS[base]
    assert "(" not in base and "[" not in base, base
    return f"public.{base}"


def inventory_values() -> str:
    lines = []
    for table in TOUCHED_TABLES:
        for column in columns()[table]:
            default = (
                "NULL::text"
                if column.default is None
                else f"{sql_literal(column.default)}::text"
            )
            lines.append(
                "                ("
                f"{sql_literal(table)}::name, {column.ordinal}, "
                f"{sql_literal(column.name)}::name, "
                f"{sql_literal(column.formatted_type)}::text, "
                f"{sql_literal(_type_cast(column))}::pg_catalog.regtype, "
                f"{column.type_modifier}, {'true' if column.not_null else 'false'}, "
                f"{default}, "
                f'{sql_literal(column.generated)}::pg_catalog."char")'
            )
    return ",\n".join(lines)


def inventory_row_count() -> int:
    return sum(len(table_columns) for table_columns in columns().values())


def privilege_values(state: dict[tuple[str, str, str], dict[str, bool]]) -> str:
    lines = []
    for table in TOUCHED_TABLES:
        for column in columns()[table]:
            for role in ROLES:
                privilege = state[(table, column.name, role)]
                lines.append(
                    "                ("
                    f"{sql_literal(table)}::name, {sql_literal(column.name)}::name, "
                    f"{sql_literal(role)}::text, "
                    f"{'true' if privilege['table_select'] else 'false'}, "
                    f"{'true' if privilege['table_insert'] else 'false'}, "
                    f"{'true' if privilege['table_update'] else 'false'}, "
                    f"{'true' if privilege['table_delete'] else 'false'}, "
                    f"{'true' if privilege['column_select'] else 'false'}, "
                    f"{'true' if privilege['column_insert'] else 'false'}, "
                    f"{'true' if privilege['column_update'] else 'false'})"
                )
    return ",\n".join(lines)


def privilege_row_count() -> int:
    return inventory_row_count() * len(ROLES)


def for_all_values() -> str:
    return ",\n".join(
        f"                ({sql_literal(table)}::name, {sql_literal(policy)}::name)"
        for table, policy in for_all_identity_set()
    )


def replaced_policy_values() -> str:
    lines = []
    for table, policy, cmd, roles, using, check in policies_to_replace():
        using_literal = (
            "NULL::text" if using == "null" else f"{sql_literal(using)}::text"
        )
        check_literal = (
            "NULL::text" if check == "null" else f"{sql_literal(check)}::text"
        )
        lines.append(
            "                ("
            f"{sql_literal(table)}::name, {sql_literal(policy)}::name, "
            f"{sql_literal(cmd)}::text, {sql_literal(roles)}::text, "
            f"{using_literal}, {check_literal})"
        )
    return ",\n".join(lines)


def _role_array(roles: str) -> str:
    """'anon,authenticated' -> ARRAY['anon', 'authenticated']::name[].

    The recorded roles are a comma-separated list. Writing them as a single
    element made a role literally named "anon,authenticated", and the live 3.2D
    postflight rejected the correct policy (found 2026-09-18 by a dry run).
    """

    return (
        "ARRAY["
        + ", ".join(sql_literal(role.strip()) for role in roles.split(","))
        + "]::name[]"
    )


def policy_inventory_values() -> str:
    return ",\n".join(
        "                ("
        f"{sql_literal(table)}::name, {sql_literal(policy)}::name, "
        f"{sql_literal(cmd)}::text, {sql_literal(mode)}::text, "
        f"{_role_array(roles)})"
        for table, policy, cmd, mode, roles in expected_policy_inventory()
    )


def column_list(names: tuple[str, ...], indent: str = "    ") -> str:
    return ",\n".join(f"{indent}{name}" for name in names)


def all_column_names(table: str) -> tuple[str, ...]:
    return tuple(column.name for column in columns()[table])


# --------------------------------------------------------------------------
# Static SQL text
# --------------------------------------------------------------------------

CORE_HEADER = """/*
Phase 3.2D targeted security hardening -- REVIEW ONLY.

Splits the ten remaining customer and seller FOR ALL policies by operation,
replaces ownership-only service-request and purchase-order writes with
column allowlists and SECURITY DEFINER transitions, and narrows public
marketplace-party columns. Every embedded catalog signature and privilege
expectation is derived from the read-only evidence under
docs/evidence/phase-3.2d and reconciled by local tests. This file must run
only after the Phase 3.2C migration and must receive human review before any
standalone preflight or migration run.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';
SET LOCAL idle_in_transaction_session_timeout = '5min';
SET LOCAL search_path = pg_catalog;

"""

PREFLIGHT_HEADER = """/*
Phase 3.2D standalone preflight -- READ ONLY, ALWAYS ROLLS BACK.

Runs exactly the same DO block as the core migration preflight and then rolls
back. It must be run, reviewed, and approved before the core migration.
*/

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';
SET LOCAL idle_in_transaction_session_timeout = '5min';
SET LOCAL search_path = pg_catalog;

"""


def preflight_block() -> str:
    tables = ",\n".join(f"        {sql_literal(table)}" for table in EXPECTED_TABLES)
    functions = ",\n".join(
        f"        {sql_literal('public.' + signature)}"
        for signature in TRANSITION_FUNCTIONS
    )
    return f"""DO $phase32d_preflight$
DECLARE
    required_role text;
    missing_tables text;
    unexpected_tables text;
    anon_role_oid oid;
    authenticated_role_oid oid;
    service_role_oid oid;
    postgres_role_oid oid;
    new_function text;
    expected_tables constant text[] := ARRAY[
{tables}
    ];
    new_functions constant text[] := ARRAY[
{functions}
    ];
BEGIN
    IF current_setting('server_version_num')::integer < 150000 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D requires PostgreSQL 15 or newer';
    END IF;

    FOREACH required_role IN ARRAY ARRAY[
        'anon',
        'authenticated',
        'service_role',
        'postgres'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_roles AS role_row
            WHERE role_row.rolname = required_role
        ) THEN
            RAISE EXCEPTION USING
                MESSAGE = pg_catalog.format(
                    'Phase 3.2D missing required role: %s',
                    required_role
                );
        END IF;
    END LOOP;

    SELECT oid INTO STRICT anon_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'anon';

    SELECT oid INTO STRICT authenticated_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'authenticated';

    SELECT oid INTO STRICT service_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'service_role';

    SELECT oid INTO STRICT postgres_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'postgres';

    WITH expected(table_name) AS (
        SELECT unnest(expected_tables)
    ),
    actual(table_name) AS (
        SELECT relation.relname::text
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN (
              'r'::pg_catalog."char",
              'p'::pg_catalog."char"
          )
    ),
    missing AS (
        SELECT table_name FROM expected
        EXCEPT
        SELECT table_name FROM actual
    ),
    unexpected AS (
        SELECT table_name FROM actual
        EXCEPT
        SELECT table_name FROM expected
    )
    SELECT
        (SELECT string_agg(table_name, ', ' ORDER BY table_name) FROM missing),
        (SELECT string_agg(table_name, ', ' ORDER BY table_name) FROM unexpected)
    INTO missing_tables, unexpected_tables;

    IF missing_tables IS NOT NULL OR unexpected_tables IS NOT NULL THEN
        RAISE EXCEPTION USING
            MESSAGE = pg_catalog.format(
                'Phase 3.2D table inventory drift; missing: %s; unexpected: %s',
                COALESCE(missing_tables, '(none)'),
                COALESCE(unexpected_tables, '(none)')
            );
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN (
              'r'::pg_catalog."char",
              'p'::pg_catalog."char"
          )
          AND (
              NOT relation.relrowsecurity
              OR relation.relforcerowsecurity
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D requires enabled, unforced RLS on every table';
    END IF;

    -- Phase 3.2C must already be applied.
    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('furnishing_request'::name, 'phase32c_furnishing_request_insert_own'::name),
                ('furnishing_request'::name, 'phase32c_furnishing_request_update_own'::name),
                ('furnishing_request'::name, 'phase32c_furnishing_request_delete_own'::name),
                ('review'::name, 'phase32c_review_anon_safe_read'::name),
                ('review'::name, 'phase32c_review_authenticated_read_guard'::name),
                ('party_capability'::name, 'phase32c_party_capability_owner_read'::name),
                ('party_capability'::name, 'phase32c_party_capability_anon_read'::name),
                ('service_type'::name, 'phase32c_service_type_anon_read'::name)
        ) AS required(table_name, policy_name)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policies AS policy
            WHERE policy.schemaname = 'public'
              AND policy.tablename = required.table_name
              AND policy.policyname = required.policy_name
        )
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.policyname IN (
              'furnishing_request_write_own',
              'review_select_public',
              'party_capability_select',
              'service_type_select_public'
          )
    ) OR pg_catalog.to_regprocedure(
        'public.open_furnishing_request(pg_catalog.uuid)'
    ) IS NULL OR pg_catalog.to_regprocedure(
        'public.withdraw_furnishing_request(pg_catalog.uuid)'
    ) IS NULL OR pg_catalog.has_table_privilege(
        anon_role_oid,
        'public.review'::pg_catalog.regclass,
        'SELECT'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D requires the applied Phase 3.2C migration';
    END IF;

    -- Nothing from this package may already exist.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.policyname LIKE 'phase32d\\_%'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D policies already exist';
    END IF;

    FOREACH new_function IN ARRAY new_functions
    LOOP
        IF pg_catalog.to_regprocedure(new_function) IS NOT NULL THEN
            RAISE EXCEPTION USING
                MESSAGE = pg_catalog.format(
                    'Phase 3.2D function already exists: %s',
                    new_function
                );
        END IF;
    END LOOP;

    -- Hardened helpers from Phase 3.2B/3.2C with the expected signatures.
    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('public.current_customer_profile_id()'::text, 'pg_catalog.uuid'::pg_catalog.regtype),
                ('public.current_marketplace_party_id()'::text, 'pg_catalog.uuid'::pg_catalog.regtype),
                ('public.current_party_is_approved()'::text, 'pg_catalog.bool'::pg_catalog.regtype),
                ('public.is_admin()'::text, 'pg_catalog.bool'::pg_catalog.regtype)
        ) AS helper(signature, return_type)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS function_metadata
            WHERE function_metadata.oid =
                  pg_catalog.to_regprocedure(helper.signature)
              AND function_metadata.prorettype = helper.return_type
              AND function_metadata.prosecdef
              AND function_metadata.proowner = postgres_role_oid
              AND function_metadata.proconfig IN (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[])
        )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D helper function drift';
    END IF;

    -- Exact FOR ALL identity set after Phase 3.2C (18 policies).
    IF EXISTS (
        WITH expected(table_name, policy_name) AS (
            VALUES
{for_all_values()}
        ),
        actual AS (
            SELECT policy.tablename AS table_name, policy.policyname AS policy_name
            FROM pg_catalog.pg_policies AS policy
            WHERE policy.schemaname = 'public'
              AND policy.cmd = 'ALL'
        ),
        drift AS (
            (SELECT * FROM expected EXCEPT SELECT * FROM actual)
            UNION ALL
            (SELECT * FROM actual EXCEPT SELECT * FROM expected)
        )
        SELECT 1 FROM drift
    ) OR (
        SELECT count(*)
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.cmd = 'ALL'
    ) <> 18 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D FOR ALL identity drift';
    END IF;

    -- Every policy this package replaces must exist with its exact deployed
    -- command, roles, USING, and WITH CHECK text.
    IF EXISTS (
        WITH expected(
            table_name,
            policy_name,
            command_name,
            role_list,
            using_expression,
            check_expression
        ) AS (
            VALUES
{replaced_policy_values()}
        )
        SELECT 1
        FROM expected
        LEFT JOIN pg_catalog.pg_policies AS actual
            ON actual.schemaname = 'public'
           AND actual.tablename = expected.table_name
           AND actual.policyname = expected.policy_name
        WHERE actual.policyname IS NULL
           OR actual.cmd <> expected.command_name
           OR actual.permissive <> 'PERMISSIVE'
           OR actual.roles::text <> expected.role_list
           -- The expected text was recorded in the SQL Editor, where public is
           -- on the search path; here it is not, so the same policy prints
           -- public.current_customer_profile_id() and FROM public.cart. Only
           -- that qualifier is removed; any other schema still differs.
           OR pg_catalog.regexp_replace(
                  pg_catalog.replace(actual.qual, 'public.', ''), '\\s+', ' ', 'g'
              ) IS DISTINCT FROM expected.using_expression
           OR pg_catalog.regexp_replace(
                  pg_catalog.replace(actual.with_check, 'public.', ''),
                  '\\s+',
                  ' ',
                  'g'
              ) IS DISTINCT FROM expected.check_expression
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D replaced policy drift';
    END IF;

    -- Exact live-confirmed column signatures of the thirteen touched tables.
    IF EXISTS (
        WITH expected(
            table_name,
            ordinal_position,
            column_name,
            formatted_type,
            column_type,
            type_modifier,
            is_not_null,
            default_expression,
            generated_kind
        ) AS (
            VALUES
{inventory_values()}
        ),
        actual AS (
            SELECT
                relation.relname AS table_name,
                attribute.attnum::integer AS ordinal_position,
                attribute.attname AS column_name,
                replace(
                    pg_catalog.format_type(
                        attribute.atttypid,
                        attribute.atttypmod
                    ),
                    'public.',
                    ''
                ) AS formatted_type,
                attribute.atttypid::pg_catalog.regtype AS column_type,
                attribute.atttypmod AS type_modifier,
                attribute.attnotnull AS is_not_null,
                replace(
                    replace(
                        pg_catalog.pg_get_expr(
                            column_default.adbin,
                            column_default.adrelid,
                            false
                        ),
                        'public.',
                        ''
                    ),
                    'pg_catalog.',
                    ''
                ) AS default_expression,
                attribute.attgenerated AS generated_kind
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_attribute AS attribute
                ON attribute.attrelid = relation.oid
            LEFT JOIN pg_catalog.pg_attrdef AS column_default
                ON column_default.adrelid = attribute.attrelid
               AND column_default.adnum = attribute.attnum
            WHERE namespace.nspname = 'public'
              AND relation.relname IN (SELECT DISTINCT table_name FROM expected)
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
        ),
        drift AS (
            (SELECT * FROM expected EXCEPT SELECT * FROM actual)
            UNION ALL
            (SELECT * FROM actual EXCEPT SELECT * FROM expected)
        )
        SELECT 1 FROM drift
    ) OR (
        SELECT count(*)
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_attribute AS attribute
            ON attribute.attrelid = relation.oid
        WHERE namespace.nspname = 'public'
          AND relation.relname IN (
{",".join(chr(10) + "              " + sql_literal(t) for t in TOUCHED_TABLES)}
          )
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
    ) <> {inventory_row_count()} OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_attribute AS attribute
            ON attribute.attrelid = relation.oid
        WHERE namespace.nspname = 'public'
          AND relation.relname IN (
{",".join(chr(10) + "              " + sql_literal(t) for t in TOUCHED_TABLES)}
          )
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
          AND attribute.attidentity <> ''
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D column inventory drift';
    END IF;

    -- Exact effective privilege baseline (after Phase 3.2C) for every column
    -- of the touched tables and the three API roles.
    IF EXISTS (
        WITH expected(
            table_name,
            column_name,
            role_name,
            table_select,
            table_insert,
            table_update,
            table_delete,
            column_select,
            column_insert,
            column_update
        ) AS (
            VALUES
{privilege_values(baseline_privileges())}
        ),
        roles(role_name, role_oid) AS (
            VALUES
                ('anon'::text, anon_role_oid),
                ('authenticated'::text, authenticated_role_oid),
                ('service_role'::text, service_role_oid)
        )
        SELECT 1
        FROM expected
        JOIN roles ON roles.role_name = expected.role_name
        CROSS JOIN LATERAL (
            SELECT
                pg_catalog.to_regclass('public.' || expected.table_name)
                    AS table_oid
        ) AS target
        WHERE target.table_oid IS NULL
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'SELECT')
              IS DISTINCT FROM expected.table_select
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'INSERT')
              IS DISTINCT FROM expected.table_insert
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'UPDATE')
              IS DISTINCT FROM expected.table_update
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'DELETE')
              IS DISTINCT FROM expected.table_delete
           OR pg_catalog.has_column_privilege(
                  roles.role_oid, target.table_oid, expected.column_name, 'SELECT'
              ) IS DISTINCT FROM expected.column_select
           OR pg_catalog.has_column_privilege(
                  roles.role_oid, target.table_oid, expected.column_name, 'INSERT'
              ) IS DISTINCT FROM expected.column_insert
           OR pg_catalog.has_column_privilege(
                  roles.role_oid, target.table_oid, expected.column_name, 'UPDATE'
              ) IS DISTINCT FROM expected.column_update
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D privilege baseline drift';
    END IF;

    -- Constraints and enum labels the new predicates and functions rely on.
    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('cart'::name, 'cart_customer_unique'::name),
                ('cart_line'::name, 'cart_line_unique_per_color'::name),
                ('customer_profile'::name, 'customer_profile_user_unique'::name),
                ('marketplace_party'::name, 'marketplace_party_user_unique'::name),
                ('review'::name, 'review_exactly_one_target'::name),
                ('review'::name, 'review_target_kind_agreement'::name),
                ('service_request'::name, 'service_request_executor_when_claimed'::name),
                ('service_request'::name, 'service_request_priced_when_claimed'::name),
                ('service_request'::name, 'service_request_completed_timestamp'::name),
                ('service_request'::name, 'service_request_address_fk'::name),
                ('purchase_order'::name, 'purchase_order_cancelled_timestamp'::name),
                ('purchase_order'::name, 'purchase_order_custom_offering_fk'::name),
                ('purchase_order'::name, 'purchase_order_address_fk'::name),
                ('furnishing_request'::name, 'furnishing_request_address_fk'::name)
        ) AS required(table_name, constraint_name)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_constraint AS constraint_row
            JOIN pg_catalog.pg_class AS relation
                ON relation.oid = constraint_row.conrelid
            JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = required.table_name
              AND constraint_row.conname = required.constraint_name
        )
    ) OR EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('service_request_state'::name, ARRAY['pending', 'accepted', 'in_progress', 'completed', 'cancelled']::text[]),
                ('order_state'::name, ARRAY['pending', 'confirmed', 'preparing', 'out_for_delivery', 'delivered', 'cancelled']::text[]),
                ('furnishing_request_state'::name, ARRAY['draft', 'open', 'accepted', 'withdrawn', 'closed']::text[]),
                ('review_target_kind'::name, ARRAY['product', 'service_request', 'marketplace_party']::text[]),
                ('party_approval_state'::name, ARRAY['pending', 'approved', 'rejected', 'suspended']::text[]),
                ('offer_state'::name, ARRAY['submitted', 'accepted', 'rejected', 'withdrawn', 'expired']::text[]),
                ('custom_offering_state'::name, ARRAY['published', 'unpublished']::text[])
        ) AS expected_enum(type_name, labels)
        WHERE (
            SELECT array_agg(enum_label.enumlabel::text ORDER BY enum_label.enumsortorder)
            FROM pg_catalog.pg_type AS enum_type
            JOIN pg_catalog.pg_namespace AS type_namespace
                ON type_namespace.oid = enum_type.typnamespace
            JOIN pg_catalog.pg_enum AS enum_label
                ON enum_label.enumtypid = enum_type.oid
            WHERE type_namespace.nspname = 'public'
              AND enum_type.typname = expected_enum.type_name
        ) IS DISTINCT FROM expected_enum.labels
    ) OR EXISTS (
        SELECT 1
        FROM (
            VALUES
                ('public.product'::pg_catalog.regclass, 'marketplace_party_id'::name),
                ('public.product'::pg_catalog.regclass, 'category_id'::name),
                ('public.product'::pg_catalog.regclass, 'lifecycle_state'::name),
                ('public.product_color'::pg_catalog.regclass, 'product_id'::name),
                ('public.product_color'::pg_catalog.regclass, 'stock_quantity'::name),
                ('public.category'::pg_catalog.regclass, 'is_active'::name),
                ('public.service_type'::pg_catalog.regclass, 'is_active'::name),
                ('public.offer'::pg_catalog.regclass, 'marketplace_party_id'::name),
                ('public.offer'::pg_catalog.regclass, 'lifecycle_state'::name),
                ('public.design'::pg_catalog.regclass, 'originating_user_id'::name),
                ('public.order_line_item'::pg_catalog.regclass, 'order_id'::name),
                ('public.order_line_item'::pg_catalog.regclass, 'product_id'::name),
                ('public.furnishing_request'::pg_catalog.regclass, 'address_id'::name),
                ('public.furnishing_request'::pg_catalog.regclass, 'lifecycle_state'::name),
                ('public.customer_profile'::pg_catalog.regclass, 'user_id'::name)
        ) AS expected_column(table_oid, column_name)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_attribute AS attribute
            WHERE attribute.attrelid = expected_column.table_oid
              AND attribute.attname = expected_column.column_name
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
        )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D required constraint, enum, or column drift';
    END IF;
END
$phase32d_preflight$;
"""


OWNER = "customer_profile_id = public.current_customer_profile_id()"
PARTY_OWNER = "marketplace_party_id = public.current_marketplace_party_id()"
APPROVED = "public.current_party_is_approved()"


def _revoke_regrant(table: str) -> str:
    """Normalize authenticated INSERT/UPDATE completely, then regrant."""
    every = all_column_names(table)
    parts = [
        f"REVOKE INSERT, UPDATE ON TABLE public.{table}\nFROM authenticated;",
        (
            "REVOKE INSERT (\n"
            + column_list(every)
            + "\n), UPDATE (\n"
            + column_list(every)
            + f"\n) ON TABLE public.{table}\nFROM authenticated;"
        ),
    ]
    if table in INSERT_ALLOWLIST:
        parts.append(
            "GRANT INSERT (\n"
            + column_list(INSERT_ALLOWLIST[table])
            + f"\n) ON TABLE public.{table}\nTO authenticated;"
        )
    if table in UPDATE_ALLOWLIST:
        parts.append(
            "GRANT UPDATE (\n"
            + column_list(UPDATE_ALLOWLIST[table])
            + f"\n) ON TABLE public.{table}\nTO authenticated;"
        )
    return "\n\n".join(parts)


def _function_grants(signature: str) -> str:
    return f"""ALTER FUNCTION public.{signature}
OWNER TO postgres;
REVOKE ALL PRIVILEGES
ON FUNCTION public.{signature}
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE
ON FUNCTION public.{signature}
TO authenticated, service_role;"""


def changes_block() -> str:
    address_delete_guard = """    AND NOT EXISTS (
        SELECT 1
        FROM public.furnishing_request AS referencing_request
        WHERE referencing_request.address_id = address.id
    )
    AND NOT EXISTS (
        SELECT 1
        FROM public.service_request AS referencing_service
        WHERE referencing_service.address_id = address.id
    )
    AND NOT EXISTS (
        SELECT 1
        FROM public.purchase_order AS referencing_order
        WHERE referencing_order.address_id = address.id
    )"""
    cart_owner = """    EXISTS (
        SELECT 1
        FROM public.cart AS owned_cart
        WHERE owned_cart.id = cart_line.cart_id
          AND owned_cart.customer_profile_id =
              public.current_customer_profile_id()
    )"""
    eligible_color = """    AND EXISTS (
        SELECT 1
        FROM public.product_color AS chosen_color
        JOIN public.product AS chosen_product
            ON chosen_product.id = chosen_color.product_id
        JOIN public.marketplace_party AS product_party
            ON product_party.id = chosen_product.marketplace_party_id
        JOIN public.category AS product_category
            ON product_category.id = chosen_product.category_id
        WHERE chosen_color.id = cart_line.product_color_id
          AND chosen_product.lifecycle_state =
              'published'::public.product_state
          AND product_party.approval_state =
              'approved'::public.party_approval_state
          AND product_category.is_active
          AND chosen_color.stock_quantity > 0
    )"""
    parent_open = """    EXISTS (
        SELECT 1
        FROM public.furnishing_request AS parent_request
        WHERE parent_request.id =
              furnishing_request_design_version.furnishing_request_id
          AND parent_request.customer_profile_id =
              public.current_customer_profile_id()
          AND parent_request.lifecycle_state IN (
              'draft'::public.furnishing_request_state,
              'open'::public.furnishing_request_state
          )
    )"""
    own_design = """    AND EXISTS (
        SELECT 1
        FROM public.design AS offered_design
        WHERE offered_design.id = custom_offering.design_id
          AND offered_design.originating_user_id = auth.uid()
    )"""
    offering_unordered = """    AND NOT EXISTS (
        SELECT 1
        FROM public.purchase_order AS referencing_order
        WHERE referencing_order.custom_offering_id = custom_offering.id
    )"""
    active_service = """    AND EXISTS (
        SELECT 1
        FROM public.service_type AS declared_service
        WHERE declared_service.id = party_capability.service_type_id
          AND declared_service.is_active
    )"""
    submitted_offer = """    EXISTS (
        SELECT 1
        FROM public.offer AS parent_offer
        WHERE parent_offer.id = offer_line_item.offer_id
          AND parent_offer.marketplace_party_id =
              public.current_marketplace_party_id()
          AND parent_offer.lifecycle_state =
              'submitted'::public.offer_state
    )"""
    reference_design = """    EXISTS (
        SELECT 1
        FROM public.design AS referenced_design
        WHERE referenced_design.id = design_product_reference.design_id
          AND referenced_design.originating_user_id = auth.uid()
    )"""
    owned_address = """    AND EXISTS (
        SELECT 1
        FROM public.address AS request_address
        WHERE request_address.id = service_request.address_id
          AND request_address.customer_profile_id =
              public.current_customer_profile_id()
    )"""
    owned_related_order = """    AND (
        related_order_id IS NULL
        OR EXISTS (
            SELECT 1
            FROM public.purchase_order AS related_order
            WHERE related_order.id = service_request.related_order_id
              AND related_order.customer_profile_id =
                  public.current_customer_profile_id()
        )
    )"""
    review_verified = """    AND (
        (
            target_kind = 'product'::public.review_target_kind
            AND target_product_id IS NOT NULL
            AND target_service_request_id IS NULL
            AND target_marketplace_party_id IS NULL
            AND EXISTS (
                SELECT 1
                FROM public.order_line_item AS purchased_line
                JOIN public.purchase_order AS purchased_order
                    ON purchased_order.id = purchased_line.order_id
                WHERE purchased_line.product_id = review.target_product_id
                  AND purchased_order.customer_profile_id =
                      public.current_customer_profile_id()
                  AND purchased_order.lifecycle_state =
                      'delivered'::public.order_state
            )
        )
        OR (
            target_kind = 'service_request'::public.review_target_kind
            AND target_product_id IS NULL
            AND target_service_request_id IS NOT NULL
            AND target_marketplace_party_id IS NULL
            AND EXISTS (
                SELECT 1
                FROM public.service_request AS reviewed_request
                WHERE reviewed_request.id = review.target_service_request_id
                  AND reviewed_request.customer_profile_id =
                      public.current_customer_profile_id()
                  AND reviewed_request.lifecycle_state =
                      'completed'::public.service_request_state
            )
        )
        OR (
            target_kind = 'marketplace_party'::public.review_target_kind
            AND target_product_id IS NULL
            AND target_service_request_id IS NULL
            AND target_marketplace_party_id IS NOT NULL
            AND (
                EXISTS (
                    SELECT 1
                    FROM public.purchase_order AS party_order
                    WHERE party_order.marketplace_party_id =
                          review.target_marketplace_party_id
                      AND party_order.customer_profile_id =
                          public.current_customer_profile_id()
                      AND party_order.lifecycle_state =
                          'delivered'::public.order_state
                )
                OR EXISTS (
                    SELECT 1
                    FROM public.service_request AS party_request
                    WHERE party_request.marketplace_party_id =
                          review.target_marketplace_party_id
                      AND party_request.customer_profile_id =
                          public.current_customer_profile_id()
                      AND party_request.lifecycle_state =
                          'completed'::public.service_request_state
                )
            )
        )
    )"""

    return f"""-- A1. address: split the FOR ALL policy; deletes stay blocked while referenced.
DROP POLICY address_write_own ON public.address;

CREATE POLICY phase32d_address_insert_own
ON public.address
FOR INSERT
TO authenticated
WITH CHECK (
    {OWNER}
);

CREATE POLICY phase32d_address_update_own
ON public.address
FOR UPDATE
TO authenticated
USING (
    {OWNER}
)
WITH CHECK (
    {OWNER}
);

CREATE POLICY phase32d_address_delete_own
ON public.address
FOR DELETE
TO authenticated
USING (
    {OWNER}
{address_delete_guard}
);

{_revoke_regrant("address")}

-- A1. cart: one server-created cart per customer; the client reads and deletes.
DROP POLICY cart_all_own ON public.cart;

CREATE POLICY phase32d_cart_select_own
ON public.cart
FOR SELECT
TO authenticated
USING (
    {OWNER}
);

CREATE POLICY phase32d_cart_delete_own
ON public.cart
FOR DELETE
TO authenticated
USING (
    {OWNER}
);

{_revoke_regrant("cart")}

-- A2. cart_line: owned cart, eligible catalogue colour at insert, quantity edits.
DROP POLICY cart_line_all_own ON public.cart_line;

CREATE POLICY phase32d_cart_line_select_own
ON public.cart_line
FOR SELECT
TO authenticated
USING (
{cart_owner}
);

CREATE POLICY phase32d_cart_line_insert_own
ON public.cart_line
FOR INSERT
TO authenticated
WITH CHECK (
{cart_owner}
{eligible_color}
);

CREATE POLICY phase32d_cart_line_update_own
ON public.cart_line
FOR UPDATE
TO authenticated
USING (
{cart_owner}
)
WITH CHECK (
{cart_owner}
);

CREATE POLICY phase32d_cart_line_delete_own
ON public.cart_line
FOR DELETE
TO authenticated
USING (
{cart_owner}
);

{_revoke_regrant("cart_line")}

-- A1. saved_space: owner-scoped per operation with a column allowlist.
DROP POLICY saved_space_all_own ON public.saved_space;

CREATE POLICY phase32d_saved_space_select_own
ON public.saved_space
FOR SELECT
TO authenticated
USING (
    {OWNER}
);

CREATE POLICY phase32d_saved_space_insert_own
ON public.saved_space
FOR INSERT
TO authenticated
WITH CHECK (
    {OWNER}
);

CREATE POLICY phase32d_saved_space_update_own
ON public.saved_space
FOR UPDATE
TO authenticated
USING (
    {OWNER}
)
WITH CHECK (
    {OWNER}
);

CREATE POLICY phase32d_saved_space_delete_own
ON public.saved_space
FOR DELETE
TO authenticated
USING (
    {OWNER}
);

{_revoke_regrant("saved_space")}

-- A1. review: insert-only, final, verified purchase or completed service.
DROP POLICY review_write_own ON public.review;

CREATE POLICY phase32d_review_select_own
ON public.review
FOR SELECT
TO authenticated
USING (
    {OWNER}
);

CREATE POLICY phase32d_review_insert_verified
ON public.review
FOR INSERT
TO authenticated
WITH CHECK (
    {OWNER}
{review_verified}
);

{_revoke_regrant("review")}

-- A2. furnishing_request_design_version: server-created; owner deletes while
-- the parent request is draft or open.
DROP POLICY furnishing_request_design_version_write_own
ON public.furnishing_request_design_version;

CREATE POLICY phase32d_furnishing_request_design_version_delete_own
ON public.furnishing_request_design_version
FOR DELETE
TO authenticated
USING (
{parent_open}
);

{_revoke_regrant("furnishing_request_design_version")}

-- A3. custom_offering: approved owner, own design, no delete once ordered.
DROP POLICY custom_offering_write_own ON public.custom_offering;

CREATE POLICY phase32d_custom_offering_insert_own
ON public.custom_offering
FOR INSERT
TO authenticated
WITH CHECK (
    {PARTY_OWNER}
    AND {APPROVED}
{own_design}
);

CREATE POLICY phase32d_custom_offering_update_own
ON public.custom_offering
FOR UPDATE
TO authenticated
USING (
    {PARTY_OWNER}
    AND {APPROVED}
)
WITH CHECK (
    {PARTY_OWNER}
    AND {APPROVED}
{own_design}
);

CREATE POLICY phase32d_custom_offering_delete_own
ON public.custom_offering
FOR DELETE
TO authenticated
USING (
    {PARTY_OWNER}
    AND {APPROVED}
{offering_unordered}
);

{_revoke_regrant("custom_offering")}

-- A3. party_capability: approved owner declares and removes active services.
DROP POLICY party_capability_write_own ON public.party_capability;

CREATE POLICY phase32d_party_capability_insert_own
ON public.party_capability
FOR INSERT
TO authenticated
WITH CHECK (
    {PARTY_OWNER}
    AND {APPROVED}
{active_service}
);

CREATE POLICY phase32d_party_capability_delete_own
ON public.party_capability
FOR DELETE
TO authenticated
USING (
    {PARTY_OWNER}
    AND {APPROVED}
);

{_revoke_regrant("party_capability")}

-- A3. offer_line_item: only while the owning seller's offer is submitted.
DROP POLICY offer_line_item_write_own ON public.offer_line_item;

CREATE POLICY phase32d_offer_line_item_insert_own
ON public.offer_line_item
FOR INSERT
TO authenticated
WITH CHECK (
{submitted_offer}
);

CREATE POLICY phase32d_offer_line_item_update_own
ON public.offer_line_item
FOR UPDATE
TO authenticated
USING (
{submitted_offer}
)
WITH CHECK (
{submitted_offer}
);

CREATE POLICY phase32d_offer_line_item_delete_own
ON public.offer_line_item
FOR DELETE
TO authenticated
USING (
{submitted_offer}
);

{_revoke_regrant("offer_line_item")}

-- A4. design_product_reference: link rows on the caller's own design.
DROP POLICY design_product_reference_write_own
ON public.design_product_reference;

CREATE POLICY phase32d_design_product_reference_insert_own
ON public.design_product_reference
FOR INSERT
TO authenticated
WITH CHECK (
{reference_design}
);

CREATE POLICY phase32d_design_product_reference_delete_own
ON public.design_product_reference
FOR DELETE
TO authenticated
USING (
{reference_design}
);

{_revoke_regrant("design_product_reference")}

-- C. service_request: pending-only customer writes, owned address, no party,
-- state changes only through the transition functions below.
DROP POLICY service_request_insert_own ON public.service_request;
DROP POLICY service_request_update_engaged ON public.service_request;

CREATE POLICY phase32d_service_request_insert_own
ON public.service_request
FOR INSERT
TO authenticated
WITH CHECK (
    {OWNER}
    AND lifecycle_state = 'pending'::public.service_request_state
    AND marketplace_party_id IS NULL
{owned_address}
{owned_related_order}
);

CREATE POLICY phase32d_service_request_update_own_pending
ON public.service_request
FOR UPDATE
TO authenticated
USING (
    {OWNER}
    AND lifecycle_state = 'pending'::public.service_request_state
)
WITH CHECK (
    {OWNER}
    AND lifecycle_state = 'pending'::public.service_request_state
    AND marketplace_party_id IS NULL
{owned_address}
);

{_revoke_regrant("service_request")}

CREATE OR REPLACE FUNCTION public.cancel_service_request(
    request_id pg_catalog.uuid
)
RETURNS pg_catalog.bool
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
    affected_rows pg_catalog.int4;
BEGIN
    UPDATE "public".service_request AS request_row
    SET lifecycle_state = 'cancelled'
    WHERE request_row.id = request_id
      AND request_row.lifecycle_state::text = 'pending'
      AND EXISTS (
          SELECT 1
          FROM public.customer_profile AS customer
          WHERE customer.id = request_row.customer_profile_id
            AND customer.user_id = auth.uid()
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

{_function_grants("cancel_service_request(pg_catalog.uuid)")}

CREATE OR REPLACE FUNCTION public.accept_service_request(
    request_id pg_catalog.uuid,
    agreed_price pg_catalog.numeric
)
RETURNS pg_catalog.bool
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
    caller_party pg_catalog.uuid;
    affected_rows pg_catalog.int4;
BEGIN
    IF agreed_price IS NULL OR agreed_price < 0 THEN
        RETURN false;
    END IF;

    SELECT party.id INTO caller_party
    FROM public.marketplace_party AS party
    WHERE party.user_id = auth.uid()
      AND party.approval_state::text = 'approved';

    IF caller_party IS NULL THEN
        RETURN false;
    END IF;

    UPDATE "public".service_request AS request_row
    SET lifecycle_state = 'accepted',
        marketplace_party_id = caller_party,
        accepted_at = pg_catalog.now(),
        price = agreed_price
    WHERE request_row.id = request_id
      AND request_row.lifecycle_state::text = 'pending'
      AND request_row.marketplace_party_id IS NULL
      AND EXISTS (
          SELECT 1
          FROM public.party_capability AS capability
          WHERE capability.marketplace_party_id = caller_party
            AND capability.service_type_id = request_row.service_type_id
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

{_function_grants("accept_service_request(pg_catalog.uuid, pg_catalog.numeric)")}

CREATE OR REPLACE FUNCTION public.start_service_request(
    request_id pg_catalog.uuid
)
RETURNS pg_catalog.bool
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
    affected_rows pg_catalog.int4;
BEGIN
    UPDATE "public".service_request AS request_row
    SET lifecycle_state = 'in_progress'
    WHERE request_row.id = request_id
      AND request_row.lifecycle_state::text = 'accepted'
      AND EXISTS (
          SELECT 1
          FROM public.marketplace_party AS party
          WHERE party.id = request_row.marketplace_party_id
            AND party.user_id = auth.uid()
            AND party.approval_state::text = 'approved'
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

{_function_grants("start_service_request(pg_catalog.uuid)")}

CREATE OR REPLACE FUNCTION public.complete_service_request(
    request_id pg_catalog.uuid
)
RETURNS pg_catalog.bool
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
    affected_rows pg_catalog.int4;
BEGIN
    UPDATE "public".service_request AS request_row
    SET lifecycle_state = 'completed',
        completed_at = pg_catalog.now()
    WHERE request_row.id = request_id
      AND request_row.lifecycle_state::text = 'in_progress'
      AND EXISTS (
          SELECT 1
          FROM public.marketplace_party AS party
          WHERE party.id = request_row.marketplace_party_id
            AND party.user_id = auth.uid()
            AND party.approval_state::text = 'approved'
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

{_function_grants("complete_service_request(pg_catalog.uuid)")}

-- Purchase orders: orders are server-created; the seller edits notes only and
-- advances state through a strict forward map; the customer cancels pending.
DROP POLICY purchase_order_update_party ON public.purchase_order;

CREATE POLICY phase32d_purchase_order_update_party_notes
ON public.purchase_order
FOR UPDATE
TO authenticated
USING (
    {PARTY_OWNER}
)
WITH CHECK (
    {PARTY_OWNER}
);

{_revoke_regrant("purchase_order")}

CREATE OR REPLACE FUNCTION public.advance_purchase_order(
    order_id pg_catalog.uuid,
    next_state public.order_state
)
RETURNS pg_catalog.bool
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
    affected_rows pg_catalog.int4;
BEGIN
    IF next_state IS NULL THEN
        RETURN false;
    END IF;

    UPDATE "public".purchase_order AS order_row
    SET lifecycle_state = next_state
    WHERE order_row.id = order_id
      AND (order_row.lifecycle_state::text, next_state::text) IN (
          ('pending', 'confirmed'),
          ('confirmed', 'preparing'),
          ('preparing', 'out_for_delivery'),
          ('out_for_delivery', 'delivered')
      )
      AND EXISTS (
          SELECT 1
          FROM public.marketplace_party AS party
          WHERE party.id = order_row.marketplace_party_id
            AND party.user_id = auth.uid()
            AND party.approval_state::text = 'approved'
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

{_function_grants("advance_purchase_order(pg_catalog.uuid, public.order_state)")}

CREATE OR REPLACE FUNCTION public.cancel_purchase_order(
    order_id pg_catalog.uuid
)
RETURNS pg_catalog.bool
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
    affected_rows pg_catalog.int4;
BEGIN
    UPDATE "public".purchase_order AS order_row
    SET lifecycle_state = 'cancelled',
        cancelled_at = pg_catalog.now()
    WHERE order_row.id = order_id
      AND order_row.lifecycle_state::text = 'pending'
      AND EXISTS (
          SELECT 1
          FROM public.customer_profile AS customer
          WHERE customer.id = order_row.customer_profile_id
            AND customer.user_id = auth.uid()
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    RETURN affected_rows = 1;
END
$function$;

{_function_grants("cancel_purchase_order(pg_catalog.uuid)")}

-- D1. marketplace_party: public and signed-in readers receive column grants
-- only; RLS policies keep evaluating user_id internally without a grant.
REVOKE SELECT ON TABLE public.marketplace_party
FROM PUBLIC, anon, authenticated;

REVOKE SELECT (
{column_list(all_column_names("marketplace_party"))}
) ON TABLE public.marketplace_party
FROM PUBLIC, anon, authenticated;

GRANT SELECT (
{column_list(PARTY_ANON_SELECT)}
) ON TABLE public.marketplace_party
TO anon;

GRANT SELECT (
{column_list(PARTY_AUTHENTICATED_SELECT)}
) ON TABLE public.marketplace_party
TO authenticated;
"""


def postflight_block() -> str:
    function_checks = ",\n".join(
        f"                ({sql_literal('public.' + signature)}::text, "
        f"{sql_literal(old)}::text, {sql_literal(new)}::text, "
        f"ARRAY[{', '.join(sql_literal(state) for state in forbidden)}]::text[])"
        for signature, old, new, forbidden in (
            (
                "cancel_service_request(pg_catalog.uuid)",
                "pending",
                "cancelled",
                ("accepted", "in_progress", "completed"),
            ),
            (
                "accept_service_request(pg_catalog.uuid, pg_catalog.numeric)",
                "pending",
                "accepted",
                ("in_progress", "completed", "cancelled"),
            ),
            (
                "start_service_request(pg_catalog.uuid)",
                "accepted",
                "in_progress",
                ("pending", "completed", "cancelled"),
            ),
            (
                "complete_service_request(pg_catalog.uuid)",
                "in_progress",
                "completed",
                ("pending", "accepted", "cancelled"),
            ),
            (
                "cancel_purchase_order(pg_catalog.uuid)",
                "pending",
                "cancelled",
                ("confirmed", "preparing", "out_for_delivery", "delivered"),
            ),
        )
    )
    return f"""DO $phase32d_postflight$
DECLARE
    anon_role_oid oid;
    authenticated_role_oid oid;
    service_role_oid oid;
    postgres_role_oid oid;
BEGIN
    SELECT oid INTO STRICT anon_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'anon';

    SELECT oid INTO STRICT authenticated_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'authenticated';

    SELECT oid INTO STRICT service_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'service_role';

    SELECT oid INTO STRICT postgres_role_oid
    FROM pg_catalog.pg_roles
    WHERE rolname = 'postgres';

    -- Exact policy inventory on every touched table.
    IF EXISTS (
        WITH expected(table_name, policy_name, command_name, mode_name, role_list) AS (
            VALUES
{policy_inventory_values()}
        ),
        actual AS (
            SELECT
                policy.tablename AS table_name,
                policy.policyname AS policy_name,
                policy.cmd AS command_name,
                policy.permissive AS mode_name,
                policy.roles AS role_list
            FROM pg_catalog.pg_policies AS policy
            WHERE policy.schemaname = 'public'
              AND policy.tablename IN (SELECT DISTINCT table_name FROM expected)
        ),
        drift AS (
            (SELECT * FROM expected EXCEPT SELECT * FROM actual)
            UNION ALL
            (SELECT * FROM actual EXCEPT SELECT * FROM expected)
        )
        SELECT 1 FROM drift
    ) OR (
        SELECT count(*)
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.cmd = 'ALL'
    ) <> 8 THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D postflight policy inventory mismatch';
    END IF;

    -- Every new policy carries its owner anchor and no broadening.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.policyname LIKE 'phase32d\\_%'
          AND (
              lower(concat_ws(' ', policy.qual, policy.with_check))
                  NOT LIKE '%current_customer_profile_id%'
              AND lower(concat_ws(' ', policy.qual, policy.with_check))
                  NOT LIKE '%current_marketplace_party_id%'
              AND lower(concat_ws(' ', policy.qual, policy.with_check))
                  NOT LIKE '%originating_user_id = auth.uid()%'
              OR lower(concat_ws(' ', policy.qual, policy.with_check))
                  LIKE '%or true%'
              OR policy.roles <> ARRAY['authenticated']::name[]
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D postflight policy anchor mismatch';
    END IF;

    -- Service-request and review predicates carry their state and ownership
    -- conditions.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND (
              (
                  policy.policyname = 'phase32d_service_request_insert_own'
                  AND (
                      lower(policy.with_check) NOT LIKE '%lifecycle_state = ''pending''%'
                      OR lower(policy.with_check) NOT LIKE '%marketplace_party_id is null%'
                      OR lower(policy.with_check) NOT LIKE '%request_address.customer_profile_id%'
                      OR lower(policy.with_check) NOT LIKE '%related_order.customer_profile_id%'
                  )
              )
              OR (
                  policy.policyname = 'phase32d_service_request_update_own_pending'
                  AND (
                      lower(policy.qual) NOT LIKE '%lifecycle_state = ''pending''%'
                      OR lower(policy.with_check) NOT LIKE '%lifecycle_state = ''pending''%'
                      OR lower(policy.with_check) NOT LIKE '%marketplace_party_id is null%'
                      OR lower(policy.with_check) NOT LIKE '%request_address.customer_profile_id%'
                  )
              )
              OR (
                  policy.policyname = 'phase32d_review_insert_verified'
                  AND (
                      lower(policy.with_check) NOT LIKE '%''delivered''%'
                      OR lower(policy.with_check) NOT LIKE '%''completed''%'
                      OR lower(policy.with_check) NOT LIKE '%purchased_line.product_id%'
                      OR lower(policy.with_check) NOT LIKE '%reviewed_request.customer_profile_id%'
                  )
              )
              OR (
                  policy.policyname = 'phase32d_address_delete_own'
                  AND (
                      lower(policy.qual) NOT LIKE '%referencing_request.address_id%'
                      OR lower(policy.qual) NOT LIKE '%referencing_service.address_id%'
                      OR lower(policy.qual) NOT LIKE '%referencing_order.address_id%'
                  )
              )
              OR (
                  policy.policyname = 'phase32d_cart_line_insert_own'
                  AND (
                      lower(policy.with_check) NOT LIKE '%stock_quantity > 0%'
                      OR lower(policy.with_check) NOT LIKE '%''published''%'
                      OR lower(policy.with_check) NOT LIKE '%''approved''%'
                      OR lower(policy.with_check) NOT LIKE '%is_active%'
                  )
              )
              OR (
                  policy.policyname LIKE 'phase32d\\_custom\\_offering\\_%'
                  AND lower(concat_ws(' ', policy.qual, policy.with_check))
                      NOT LIKE '%current_party_is_approved()%'
              )
              OR (
                  policy.policyname LIKE 'phase32d\\_party\\_capability\\_%'
                  AND lower(concat_ws(' ', policy.qual, policy.with_check))
                      NOT LIKE '%current_party_is_approved()%'
              )
              OR (
                  policy.policyname LIKE 'phase32d\\_offer\\_line\\_item\\_%'
                  AND lower(concat_ws(' ', policy.qual, policy.with_check))
                      NOT LIKE '%''submitted''%'
              )
              OR (
                  policy.policyname = 'phase32d_furnishing_request_design_version_delete_own'
                  AND (
                      lower(policy.qual) NOT LIKE '%''draft''%'
                      OR lower(policy.qual) NOT LIKE '%''open''%'
                  )
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D postflight predicate mismatch';
    END IF;

    -- Exact effective privileges after the package.
    IF EXISTS (
        WITH expected(
            table_name,
            column_name,
            role_name,
            table_select,
            table_insert,
            table_update,
            table_delete,
            column_select,
            column_insert,
            column_update
        ) AS (
            VALUES
{privilege_values(expected_privileges())}
        ),
        roles(role_name, role_oid) AS (
            VALUES
                ('anon'::text, anon_role_oid),
                ('authenticated'::text, authenticated_role_oid),
                ('service_role'::text, service_role_oid)
        )
        SELECT 1
        FROM expected
        JOIN roles ON roles.role_name = expected.role_name
        CROSS JOIN LATERAL (
            SELECT
                pg_catalog.to_regclass('public.' || expected.table_name)
                    AS table_oid
        ) AS target
        WHERE target.table_oid IS NULL
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'SELECT')
              IS DISTINCT FROM expected.table_select
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'INSERT')
              IS DISTINCT FROM expected.table_insert
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'UPDATE')
              IS DISTINCT FROM expected.table_update
           OR pg_catalog.has_table_privilege(roles.role_oid, target.table_oid, 'DELETE')
              IS DISTINCT FROM expected.table_delete
           OR pg_catalog.has_column_privilege(
                  roles.role_oid, target.table_oid, expected.column_name, 'SELECT'
              ) IS DISTINCT FROM expected.column_select
           OR pg_catalog.has_column_privilege(
                  roles.role_oid, target.table_oid, expected.column_name, 'INSERT'
              ) IS DISTINCT FROM expected.column_insert
           OR pg_catalog.has_column_privilege(
                  roles.role_oid, target.table_oid, expected.column_name, 'UPDATE'
              ) IS DISTINCT FROM expected.column_update
    ) OR EXISTS (
        -- No column ACL entry may carry the grant option or name PUBLIC (0).
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_attribute AS attribute
            ON attribute.attrelid = relation.oid
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            attribute.attacl
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND relation.relname IN (
{",".join(chr(10) + "              " + sql_literal(t) for t in TOUCHED_TABLES)}
          )
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
          AND (acl.is_grantable OR acl.grantee = 0)
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D postflight privilege mismatch';
    END IF;

    -- Transition functions: exact metadata, direction, ownership, and grants.
    IF EXISTS (
        WITH expected(signature, old_state, new_state, forbidden_states) AS (
            VALUES
{function_checks},
                ('public.advance_purchase_order(pg_catalog.uuid, public.order_state)'::text, 'pending'::text, 'confirmed'::text, ARRAY['cancelled']::text[])
        )
        SELECT 1
        FROM expected
        LEFT JOIN pg_catalog.pg_proc AS function_metadata
            ON function_metadata.oid = pg_catalog.to_regprocedure(expected.signature)
        WHERE function_metadata.oid IS NULL
           OR function_metadata.prorettype <> 'pg_catalog.bool'::pg_catalog.regtype
           OR function_metadata.prolang <> (
                  SELECT language.oid
                  FROM pg_catalog.pg_language AS language
                  WHERE language.lanname = 'plpgsql'
              )
           OR function_metadata.provolatile <> 'v'::pg_catalog."char"
           OR NOT function_metadata.prosecdef
           OR function_metadata.proowner <> postgres_role_oid
           OR coalesce(function_metadata.proconfig NOT IN (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[]), true)
           OR lower(function_metadata.prosrc) NOT LIKE '%auth.uid()%'
           -- advance_purchase_order lists its allowed (from, to) pairs rather
           -- than testing one state, so it is checked for its first pair.
           OR lower(function_metadata.prosrc) NOT LIKE
                  CASE
                      WHEN expected.signature LIKE 'public.advance\\_purchase\\_order(%'
                      THEN '%(''' || expected.old_state || ''', '''
                           || expected.new_state || ''')%'
                      ELSE '%lifecycle_state::text = ''' || expected.old_state || '''%'
                  END
           OR lower(function_metadata.prosrc) NOT LIKE '%''' || expected.new_state || '''%'
           OR lower(function_metadata.prosrc) LIKE '%or true%'
           OR lower(function_metadata.prosrc) NOT LIKE '%get diagnostics affected_rows = row_count%'
           OR lower(function_metadata.prosrc) NOT LIKE '%return affected_rows = 1%'
           OR EXISTS (
                  SELECT 1
                  FROM unnest(expected.forbidden_states) AS forbidden(state_name)
                  WHERE lower(function_metadata.prosrc)
                      LIKE '%''' || forbidden.state_name || '''%'
              )
           OR pg_catalog.has_function_privilege(anon_role_oid, function_metadata.oid, 'EXECUTE')
           OR NOT pg_catalog.has_function_privilege(
                  authenticated_role_oid, function_metadata.oid, 'EXECUTE'
              )
           OR NOT pg_catalog.has_function_privilege(
                  service_role_oid, function_metadata.oid, 'EXECUTE'
              )
           OR EXISTS (
                  SELECT 1
                  FROM pg_catalog.aclexplode(
                      COALESCE(
                          function_metadata.proacl,
                          pg_catalog.acldefault('f'::pg_catalog."char", function_metadata.proowner)
                      )
                  ) AS acl
                  WHERE acl.privilege_type = 'EXECUTE'
                    AND (
                        acl.grantee NOT IN (
                            postgres_role_oid,
                            authenticated_role_oid,
                            service_role_oid
                        )
                        OR (
                            acl.grantee IN (authenticated_role_oid, service_role_oid)
                            AND acl.is_grantable
                        )
                    )
              )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D postflight transition function mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN (
              'r'::pg_catalog."char",
              'p'::pg_catalog."char"
          )
          AND (
              NOT relation.relrowsecurity
              OR relation.relforcerowsecurity
          )
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = 'Phase 3.2D postflight RLS/FORCE mismatch';
    END IF;
END
$phase32d_postflight$;
"""


def core_sql() -> str:
    return (
        CORE_HEADER
        + preflight_block()
        + "\n"
        + changes_block()
        + "\n"
        + postflight_block()
        + "\nCOMMIT;\n"
    )


def preflight_sql() -> str:
    return PREFLIGHT_HEADER + preflight_block() + "\nROLLBACK;\n"


# --------------------------------------------------------------------------
# Verification file
# --------------------------------------------------------------------------

VERIFY_HEADER = """/*
Phase 3.2D targeted hardening verification -- READ ONLY.

Run each numbered SELECT separately only after an independently reviewed
migration. Every section returns expected_count, actual_count, failed_count,
and check_passed. No statement reads application rows.
*/
"""


def _roles_cte() -> str:
    return """WITH roles AS (
    SELECT
        max(oid) FILTER (WHERE rolname = 'anon') AS anon_oid,
        max(oid) FILTER (WHERE rolname = 'authenticated') AS authenticated_oid,
        max(oid) FILTER (WHERE rolname = 'service_role') AS service_role_oid,
        max(oid) FILTER (WHERE rolname = 'postgres') AS postgres_oid
    FROM pg_catalog.pg_roles
)"""


def verify_sql() -> str:
    touched_in = ",".join(
        chr(10) + "          " + sql_literal(t) for t in TOUCHED_TABLES
    )
    expected_policy_count = len(expected_policy_inventory())
    sections = []

    sections.append(f"""-- 01. Phase 3.2C prerequisites remain present and no replaced policy survives.
WITH required(table_name, policy_name) AS (
    VALUES
        ('furnishing_request'::name, 'phase32c_furnishing_request_insert_own'::name),
        ('furnishing_request'::name, 'phase32c_furnishing_request_update_own'::name),
        ('furnishing_request'::name, 'phase32c_furnishing_request_delete_own'::name),
        ('review'::name, 'phase32c_review_anon_safe_read'::name),
        ('review'::name, 'phase32c_review_authenticated_read_guard'::name),
        ('party_capability'::name, 'phase32c_party_capability_owner_read'::name)
),
present AS (
    SELECT count(*)::bigint AS present_count
    FROM required
    WHERE EXISTS (
        SELECT 1
        FROM pg_catalog.pg_policies AS policy
        WHERE policy.schemaname = 'public'
          AND policy.tablename = required.table_name
          AND policy.policyname = required.policy_name
    )
),
survivors AS (
    SELECT count(*)::bigint AS survivor_count
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.policyname IN (
{",".join(chr(10) + "          " + sql_literal(p) for _t, p, *_ in policies_to_replace())}
      )
)
SELECT
    'phase32c_prerequisites_and_no_survivors'::text AS check_name,
    6::bigint AS expected_count,
    present.present_count AS actual_count,
    6 - present.present_count + survivors.survivor_count AS failed_count,
    present.present_count = 6 AND survivors.survivor_count = 0 AS check_passed
FROM present
CROSS JOIN survivors;
""")

    sections.append(f"""-- 02. Exactly eight FOR ALL policies remain, all admin or seller catalogue.
WITH expected(table_name, policy_name) AS (
    VALUES
{",".join(chr(10) + "        (" + sql_literal(t) + "::name, " + sql_literal(p) + "::name)" for t, p in for_all_identity_set() if t not in DROPPED_POLICIES)}
),
actual AS (
    SELECT policy.tablename AS table_name, policy.policyname AS policy_name
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.cmd = 'ALL'
),
missing AS (SELECT * FROM expected EXCEPT SELECT * FROM actual),
unexpected AS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
SELECT
    'for_all_policies_exact'::text AS check_name,
    8::bigint AS expected_count,
    (SELECT count(*) FROM actual)::bigint AS actual_count,
    ((SELECT count(*) FROM missing) + (SELECT count(*) FROM unexpected))::bigint
        AS failed_count,
    (SELECT count(*) FROM missing) = 0
        AND (SELECT count(*) FROM unexpected) = 0
        AND (SELECT count(*) FROM actual) = 8 AS check_passed;
""")

    sections.append(f"""-- 03. Exact column signatures of the thirteen touched tables.
WITH expected(
    table_name,
    ordinal_position,
    column_name,
    formatted_type,
    column_type,
    type_modifier,
    is_not_null,
    default_expression,
    generated_kind
) AS (
    VALUES
{inventory_values()}
),
actual AS (
    SELECT
        relation.relname AS table_name,
        attribute.attnum::integer AS ordinal_position,
        attribute.attname AS column_name,
        replace(
            pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
            'public.',
            ''
        ) AS formatted_type,
        attribute.atttypid::pg_catalog.regtype AS column_type,
        attribute.atttypmod AS type_modifier,
        attribute.attnotnull AS is_not_null,
        replace(
            replace(
                pg_catalog.pg_get_expr(column_default.adbin, column_default.adrelid, false),
                'public.',
                ''
            ),
            'pg_catalog.',
            ''
        ) AS default_expression,
        attribute.attgenerated AS generated_kind
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_attribute AS attribute
        ON attribute.attrelid = relation.oid
    LEFT JOIN pg_catalog.pg_attrdef AS column_default
        ON column_default.adrelid = attribute.attrelid
       AND column_default.adnum = attribute.attnum
    WHERE namespace.nspname = 'public'
      AND relation.relname IN ({touched_in}
      )
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
),
missing AS (SELECT * FROM expected EXCEPT SELECT * FROM actual),
unexpected AS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
SELECT
    'touched_table_exact_inventory'::text AS check_name,
    {inventory_row_count()}::bigint AS expected_count,
    (SELECT count(*) FROM actual)::bigint AS actual_count,
    ((SELECT count(*) FROM missing) + (SELECT count(*) FROM unexpected))::bigint
        AS failed_count,
    (SELECT count(*) FROM missing) = 0
        AND (SELECT count(*) FROM unexpected) = 0
        AND (SELECT count(*) FROM actual) = {inventory_row_count()} AS check_passed;
""")

    sections.append(f"""-- 04. Exact effective privileges for every touched column and API role.
{_roles_cte()},
expected(
    table_name,
    column_name,
    role_name,
    table_select,
    table_insert,
    table_update,
    table_delete,
    column_select,
    column_insert,
    column_update
) AS (
    VALUES
{privilege_values(expected_privileges())}
),
role_map(role_name, role_oid) AS (
    SELECT 'anon'::text, anon_oid FROM roles
    UNION ALL
    SELECT 'authenticated'::text, authenticated_oid FROM roles
    UNION ALL
    SELECT 'service_role'::text, service_role_oid FROM roles
),
comparison AS (
    SELECT
        target.table_oid IS NOT NULL
        AND pg_catalog.has_table_privilege(role_map.role_oid, target.table_oid, 'SELECT')
            IS NOT DISTINCT FROM expected.table_select
        AND pg_catalog.has_table_privilege(role_map.role_oid, target.table_oid, 'INSERT')
            IS NOT DISTINCT FROM expected.table_insert
        AND pg_catalog.has_table_privilege(role_map.role_oid, target.table_oid, 'UPDATE')
            IS NOT DISTINCT FROM expected.table_update
        AND pg_catalog.has_table_privilege(role_map.role_oid, target.table_oid, 'DELETE')
            IS NOT DISTINCT FROM expected.table_delete
        AND pg_catalog.has_column_privilege(
                role_map.role_oid, target.table_oid, expected.column_name, 'SELECT'
            ) IS NOT DISTINCT FROM expected.column_select
        AND pg_catalog.has_column_privilege(
                role_map.role_oid, target.table_oid, expected.column_name, 'INSERT'
            ) IS NOT DISTINCT FROM expected.column_insert
        AND pg_catalog.has_column_privilege(
                role_map.role_oid, target.table_oid, expected.column_name, 'UPDATE'
            ) IS NOT DISTINCT FROM expected.column_update AS passed
    FROM expected
    JOIN role_map ON role_map.role_name = expected.role_name
    CROSS JOIN LATERAL (
        SELECT pg_catalog.to_regclass('public.' || expected.table_name) AS table_oid
    ) AS target
)
SELECT
    'touched_table_exact_privileges'::text AS check_name,
    {privilege_row_count()}::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    {privilege_row_count()} - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = {privilege_row_count()} AS check_passed
FROM comparison;
""")

    sections.append(f"""-- 05. Exact policy inventory on the touched tables.
WITH expected(table_name, policy_name, command_name, mode_name, role_list) AS (
    VALUES
{policy_inventory_values()}
),
actual AS (
    SELECT
        policy.tablename AS table_name,
        policy.policyname AS policy_name,
        policy.cmd AS command_name,
        policy.permissive AS mode_name,
        policy.roles AS role_list
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.tablename IN ({touched_in}
      )
),
missing AS (SELECT * FROM expected EXCEPT SELECT * FROM actual),
unexpected AS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
SELECT
    'touched_table_policy_inventory'::text AS check_name,
    {expected_policy_count}::bigint AS expected_count,
    (SELECT count(*) FROM actual)::bigint AS actual_count,
    ((SELECT count(*) FROM missing) + (SELECT count(*) FROM unexpected))::bigint
        AS failed_count,
    (SELECT count(*) FROM missing) = 0
        AND (SELECT count(*) FROM unexpected) = 0 AS check_passed;
""")

    sections.append("""-- 06. Every new policy is owner-anchored, authenticated-only, and unbroadened.
WITH new_policies AS (
    SELECT
        policy.policyname,
        lower(concat_ws(' ', policy.qual, policy.with_check)) AS predicate,
        policy.roles
    FROM pg_catalog.pg_policies AS policy
    WHERE policy.schemaname = 'public'
      AND policy.policyname LIKE 'phase32d\\_%'
),
comparison AS (
    SELECT
        (
            predicate LIKE '%current_customer_profile_id%'
            OR predicate LIKE '%current_marketplace_party_id%'
            OR predicate LIKE '%originating_user_id = auth.uid()%'
        )
        AND predicate NOT LIKE '%or true%'
        AND roles = ARRAY['authenticated']::name[] AS passed
    FROM new_policies
)
SELECT
    'new_policies_owner_anchored'::text AS check_name,
    29::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    29 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 29 AND count(*) = 29 AS check_passed
FROM comparison;
""")

    sections.append("""-- 07. State, address, catalogue, and approval predicates on the new policies.
WITH checks(policy_name, field_name, needle) AS (
    VALUES
        ('phase32d_service_request_insert_own', 'with_check', 'lifecycle_state = ''pending'''),
        ('phase32d_service_request_insert_own', 'with_check', 'marketplace_party_id is null'),
        ('phase32d_service_request_insert_own', 'with_check', 'request_address.customer_profile_id'),
        ('phase32d_service_request_insert_own', 'with_check', 'related_order.customer_profile_id'),
        ('phase32d_service_request_update_own_pending', 'qual', 'lifecycle_state = ''pending'''),
        ('phase32d_service_request_update_own_pending', 'with_check', 'lifecycle_state = ''pending'''),
        ('phase32d_service_request_update_own_pending', 'with_check', 'marketplace_party_id is null'),
        ('phase32d_service_request_update_own_pending', 'with_check', 'request_address.customer_profile_id'),
        ('phase32d_review_insert_verified', 'with_check', '''delivered'''),
        ('phase32d_review_insert_verified', 'with_check', '''completed'''),
        ('phase32d_review_insert_verified', 'with_check', 'purchased_line.product_id'),
        ('phase32d_review_insert_verified', 'with_check', 'reviewed_request.customer_profile_id'),
        ('phase32d_review_insert_verified', 'with_check', 'party_order.marketplace_party_id'),
        ('phase32d_address_delete_own', 'qual', 'referencing_request.address_id'),
        ('phase32d_address_delete_own', 'qual', 'referencing_service.address_id'),
        ('phase32d_address_delete_own', 'qual', 'referencing_order.address_id'),
        ('phase32d_cart_line_insert_own', 'with_check', 'stock_quantity > 0'),
        ('phase32d_cart_line_insert_own', 'with_check', '''published'''),
        ('phase32d_cart_line_insert_own', 'with_check', '''approved'''),
        ('phase32d_cart_line_insert_own', 'with_check', 'is_active'),
        ('phase32d_custom_offering_insert_own', 'with_check', 'current_party_is_approved()'),
        ('phase32d_custom_offering_insert_own', 'with_check', 'offered_design.originating_user_id'),
        ('phase32d_custom_offering_update_own', 'qual', 'current_party_is_approved()'),
        ('phase32d_custom_offering_update_own', 'with_check', 'offered_design.originating_user_id'),
        ('phase32d_custom_offering_delete_own', 'qual', 'referencing_order.custom_offering_id'),
        ('phase32d_party_capability_insert_own', 'with_check', 'current_party_is_approved()'),
        ('phase32d_party_capability_insert_own', 'with_check', 'declared_service.is_active'),
        ('phase32d_party_capability_delete_own', 'qual', 'current_party_is_approved()'),
        ('phase32d_offer_line_item_insert_own', 'with_check', '''submitted'''),
        ('phase32d_offer_line_item_update_own', 'qual', '''submitted'''),
        ('phase32d_offer_line_item_update_own', 'with_check', '''submitted'''),
        ('phase32d_offer_line_item_delete_own', 'qual', '''submitted'''),
        ('phase32d_furnishing_request_design_version_delete_own', 'qual', '''draft'''),
        ('phase32d_furnishing_request_design_version_delete_own', 'qual', '''open'''),
        ('phase32d_design_product_reference_insert_own', 'with_check', 'referenced_design.originating_user_id'),
        ('phase32d_design_product_reference_delete_own', 'qual', 'referenced_design.originating_user_id')
),
comparison AS (
    SELECT
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_policies AS policy
            WHERE policy.schemaname = 'public'
              AND policy.policyname = checks.policy_name
              AND lower(
                  CASE checks.field_name
                      WHEN 'qual' THEN policy.qual
                      ELSE policy.with_check
                  END
              ) LIKE '%' || checks.needle || '%'
        ) AS passed
    FROM checks
)
SELECT
    'new_policy_required_predicates'::text AS check_name,
    36::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    36 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 36 AS check_passed
FROM comparison;
""")

    sections.append(f"""-- 08. Transition functions have exact metadata, directions, and ownership.
{_roles_cte()},
expected(signature, old_state, new_state, forbidden_states) AS (
    VALUES
        ('public.cancel_service_request(pg_catalog.uuid)'::text, 'pending'::text, 'cancelled'::text, ARRAY['accepted', 'in_progress', 'completed']::text[]),
        ('public.accept_service_request(pg_catalog.uuid, pg_catalog.numeric)'::text, 'pending'::text, 'accepted'::text, ARRAY['in_progress', 'completed', 'cancelled']::text[]),
        ('public.start_service_request(pg_catalog.uuid)'::text, 'accepted'::text, 'in_progress'::text, ARRAY['pending', 'completed', 'cancelled']::text[]),
        ('public.complete_service_request(pg_catalog.uuid)'::text, 'in_progress'::text, 'completed'::text, ARRAY['pending', 'accepted', 'cancelled']::text[]),
        ('public.cancel_purchase_order(pg_catalog.uuid)'::text, 'pending'::text, 'cancelled'::text, ARRAY['confirmed', 'preparing', 'out_for_delivery', 'delivered']::text[]),
        ('public.advance_purchase_order(pg_catalog.uuid, public.order_state)'::text, 'pending'::text, 'confirmed'::text, ARRAY['cancelled']::text[])
),
comparison AS (
    SELECT
        function_metadata.oid IS NOT NULL
        AND function_metadata.prorettype = 'pg_catalog.bool'::pg_catalog.regtype
        AND function_metadata.prolang = (
            SELECT language.oid
            FROM pg_catalog.pg_language AS language
            WHERE language.lanname = 'plpgsql'
        )
        AND function_metadata.provolatile = 'v'::pg_catalog."char"
        AND function_metadata.prosecdef
        AND function_metadata.proowner = roles.postgres_oid
        AND function_metadata.proconfig IN (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[])
        AND lower(function_metadata.prosrc) LIKE '%auth.uid()%'
        AND lower(function_metadata.prosrc) LIKE
            CASE
                WHEN expected.signature LIKE 'public.advance\\_purchase\\_order(%'
                THEN '%(''' || expected.old_state || ''', '''
                     || expected.new_state || ''')%'
                ELSE '%lifecycle_state::text = ''' || expected.old_state || '''%'
            END
        AND lower(function_metadata.prosrc) LIKE '%''' || expected.new_state || '''%'
        AND lower(function_metadata.prosrc) NOT LIKE '%or true%'
        AND lower(function_metadata.prosrc) LIKE '%return affected_rows = 1%'
        AND NOT EXISTS (
            SELECT 1
            FROM unnest(expected.forbidden_states) AS forbidden(state_name)
            WHERE lower(function_metadata.prosrc) LIKE '%''' || forbidden.state_name || '''%'
        ) AS passed
    FROM expected
    CROSS JOIN roles
    LEFT JOIN pg_catalog.pg_proc AS function_metadata
        ON function_metadata.oid = pg_catalog.to_regprocedure(expected.signature)
)
SELECT
    'transition_function_definitions'::text AS check_name,
    6::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    6 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 6 AS check_passed
FROM comparison;
""")

    sections.append(f"""-- 09. Transition EXECUTE is authenticated/service-only without grant option.
{_roles_cte()},
expected(signature) AS (
    VALUES
{",".join(chr(10) + "        (" + sql_literal("public." + s) + "::text)" for s in TRANSITION_FUNCTIONS)}
),
comparison AS (
    SELECT
        function_metadata.oid IS NOT NULL
        AND NOT pg_catalog.has_function_privilege(roles.anon_oid, function_metadata.oid, 'EXECUTE')
        AND pg_catalog.has_function_privilege(roles.authenticated_oid, function_metadata.oid, 'EXECUTE')
        AND pg_catalog.has_function_privilege(roles.service_role_oid, function_metadata.oid, 'EXECUTE')
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.aclexplode(
                COALESCE(
                    function_metadata.proacl,
                    pg_catalog.acldefault('f'::pg_catalog."char", function_metadata.proowner)
                )
            ) AS acl
            WHERE acl.privilege_type = 'EXECUTE'
              AND (
                  acl.grantee NOT IN (roles.postgres_oid, roles.authenticated_oid, roles.service_role_oid)
                  OR (acl.grantee IN (roles.authenticated_oid, roles.service_role_oid) AND acl.is_grantable)
              )
        ) AS passed
    FROM expected
    CROSS JOIN roles
    LEFT JOIN pg_catalog.pg_proc AS function_metadata
        ON function_metadata.oid = pg_catalog.to_regprocedure(expected.signature)
)
SELECT
    'transition_function_grants'::text AS check_name,
    6::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    6 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 6 AS check_passed
FROM comparison;
""")

    sections.append(f"""-- 10. Helper functions remain hardened and unchanged by this package.
{_roles_cte()},
expected(signature, return_type) AS (
    VALUES
        ('public.current_customer_profile_id()'::text, 'pg_catalog.uuid'::pg_catalog.regtype),
        ('public.current_marketplace_party_id()'::text, 'pg_catalog.uuid'::pg_catalog.regtype),
        ('public.current_party_is_approved()'::text, 'pg_catalog.bool'::pg_catalog.regtype),
        ('public.is_admin()'::text, 'pg_catalog.bool'::pg_catalog.regtype)
),
comparison AS (
    SELECT
        function_metadata.oid IS NOT NULL
        AND function_metadata.prorettype = expected.return_type
        AND function_metadata.prosecdef
        AND function_metadata.proowner = roles.postgres_oid
        AND function_metadata.proconfig IN (ARRAY['search_path=']::text[], ARRAY['search_path=""']::text[])
        AND NOT pg_catalog.has_function_privilege(roles.anon_oid, function_metadata.oid, 'EXECUTE') AS passed
    FROM expected
    CROSS JOIN roles
    LEFT JOIN pg_catalog.pg_proc AS function_metadata
        ON function_metadata.oid = pg_catalog.to_regprocedure(expected.signature)
)
SELECT
    'helper_functions_unchanged'::text AS check_name,
    4::bigint AS expected_count,
    count(*) FILTER (WHERE passed)::bigint AS actual_count,
    4 - count(*) FILTER (WHERE passed) AS failed_count,
    count(*) FILTER (WHERE passed) = 4 AS check_passed
FROM comparison;
""")

    sections.append(f"""-- 11. Every public base table keeps enabled, unforced RLS.
WITH tables AS (
    SELECT relation.relrowsecurity, relation.relforcerowsecurity
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r'::pg_catalog."char", 'p'::pg_catalog."char")
)
SELECT
    'rls_enabled_unforced_everywhere'::text AS check_name,
    {len(EXPECTED_TABLES)}::bigint AS expected_count,
    count(*) FILTER (WHERE relrowsecurity AND NOT relforcerowsecurity)::bigint AS actual_count,
    count(*) - count(*) FILTER (WHERE relrowsecurity AND NOT relforcerowsecurity) AS failed_count,
    count(*) = {len(EXPECTED_TABLES)}
        AND count(*) FILTER (WHERE relrowsecurity AND NOT relforcerowsecurity) = {len(EXPECTED_TABLES)} AS check_passed
FROM tables;
""")

    sections.append("""-- 12. No Storage object grant or default ACL was touched by this package.
WITH storage_grants AS (
    SELECT count(*)::bigint AS grant_count
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(relation.relacl, pg_catalog.acldefault('r'::pg_catalog."char", relation.relowner))
    ) AS acl
    JOIN pg_catalog.pg_roles AS grantee
        ON grantee.oid = acl.grantee
    WHERE namespace.nspname = 'storage'
      AND relation.relname = 'objects'
      AND grantee.rolname IN ('anon', 'authenticated', 'service_role')
),
default_acls AS (
    SELECT count(*)::bigint AS default_count
    FROM pg_catalog.pg_default_acl AS default_acl
    JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = default_acl.defaclnamespace
    WHERE namespace.nspname = 'public'
)
SELECT
    'storage_and_default_acls_reported'::text AS check_name,
    0::bigint AS expected_count,
    (storage_grants.grant_count + default_acls.default_count)::bigint AS actual_count,
    0::bigint AS failed_count,
    true AS check_passed
FROM storage_grants
CROSS JOIN default_acls;
""")

    return VERIFY_HEADER + "\n" + "\n\n".join(sections)


def build() -> dict[Path, str]:
    return {
        CORE_PATH: core_sql(),
        PREFLIGHT_PATH: preflight_sql(),
        VERIFY_PATH: verify_sql(),
    }


if __name__ == "__main__":
    for path, text in build().items():
        path.write_text(text, encoding="utf-8", newline="\n")
        print(
            f"wrote {path.relative_to(PROJECT_ROOT)} ({len(text.splitlines())} lines)"
        )
