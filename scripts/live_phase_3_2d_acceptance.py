"""Secure live acceptance checks for the review-only Phase 3.2D proposal.

This utility is intentionally not part of the application. It reuses the safe
interactive/authentication, read, and no-op PATCH primitives from Phase 3.2B
and must only be run after the reviewed Phase 3.2C and 3.2D migrations are
applied to a fake-data test branch.

It performs GET and value-preserving PATCH requests only. It never inserts,
deletes, changes a lifecycle state, or names the transition functions; those
are verified by the SQL verification file, not here.
"""

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, NoReturn

import httpx
from pydantic import SecretStr

from app.config import Settings, load_settings
from scripts import live_rls_acceptance as base

ADDRESS_FIELDS = (
    "id",
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
)
CART_FIELDS = ("id", "customer_profile_id")
CART_LINE_FIELDS = ("id", "cart_id", "product_color_id", "quantity")
SAVED_SPACE_FIELDS = (
    "id",
    "customer_profile_id",
    "space_name",
    "width_cm",
    "depth_cm",
    "measurement_source",
)
REVIEW_FIELDS = (
    "id",
    "customer_profile_id",
    "target_kind",
    "target_product_id",
    "target_service_request_id",
    "target_marketplace_party_id",
    "rating",
    "comment",
    "created_at",
)
SERVICE_REQUEST_FIELDS = (
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
)
PURCHASE_ORDER_FIELDS = (
    "id",
    "customer_profile_id",
    "marketplace_party_id",
    "address_id",
    "origin",
    "offer_id",
    "custom_offering_id",
    "service_request_id",
    "settlement_id",
    "lifecycle_state",
    "order_discount_amount",
    "delivery_fee",
    "required_upfront_amount",
    "notes",
    "placed_at",
    "cancelled_at",
    "ship_recipient_name",
    "ship_contact_phone",
    "ship_address_line_1",
    "ship_address_line_2",
    "ship_city",
    "ship_country",
    "ship_latitude",
    "ship_longitude",
)
CUSTOM_OFFERING_FIELDS = (
    "id",
    "marketplace_party_id",
    "design_id",
    "published_price",
    "title",
    "description",
    "publication_state",
    "published_at",
)
OFFER_LINE_ITEM_FIELDS = (
    "id",
    "offer_id",
    "line_kind",
    "product_id",
    "item_name",
    "specification",
    "unit_price",
    "quantity",
    "line_total",
    "display_order",
)
PARTY_CAPABILITY_FIELDS = ("marketplace_party_id", "service_type_id", "declared_at")
DESIGN_PRODUCT_REFERENCE_FIELDS = ("design_id", "product_id")
FURNISHING_REQUEST_DESIGN_VERSION_FIELDS = (
    "furnishing_request_id",
    "design_version_id",
)
PARTY_PUBLIC_FIELDS = (
    "id",
    "business_name",
    "business_description",
    "logo_url",
    "coverage_area",
    "approval_state",
)
PARTY_AUTHENTICATED_FIELDS = PARTY_PUBLIC_FIELDS + ("state_reason",)
PARTY_HIDDEN_COLUMN = "user_id"
PENDING_SERVICE_STATE = "pending"
LOCKED_SERVICE_STATES = ("accepted", "in_progress", "completed", "cancelled")
SUBMITTED_OFFER_STATE = "submitted"
MAX_ACCEPTANCE_ROWS = 100

Probe = tuple[str, str, bool, str]
"""(snapshot attribute, column, allowed, check label)."""


@dataclass(frozen=True, slots=True)
class LinkRow:
    """A private snapshot of a composite-key link row."""

    relation: str
    fields: tuple[str, ...]
    key: Mapping[str, SecretStr]
    values: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CustomerFixtures:
    """Every customer-owned row read before the first customer PATCH."""

    address: base.RecordSnapshot
    cart: base.RecordSnapshot
    cart_line: base.RecordSnapshot
    saved_space: base.RecordSnapshot
    review: base.RecordSnapshot
    pending_request: base.RecordSnapshot
    locked_request: base.RecordSnapshot
    order: base.RecordSnapshot
    design_reference: LinkRow
    request_design_version: LinkRow


@dataclass(frozen=True, slots=True)
class SellerFixtures:
    """Every seller-owned row read before the first seller PATCH."""

    offering: base.RecordSnapshot
    submitted_line: base.RecordSnapshot
    locked_line: base.RecordSnapshot
    order: base.RecordSnapshot
    capability: LinkRow


CUSTOMER_PROBES: tuple[Probe, ...] = (
    ("address", "label", True, "customer_address_editable_noop"),
    ("address", "customer_profile_id", False, "customer_address_owner_denial"),
    ("cart", "customer_profile_id", False, "customer_cart_update_denial"),
    ("cart_line", "quantity", True, "customer_cart_line_editable_noop"),
    ("cart_line", "cart_id", False, "customer_cart_line_parent_denial"),
    ("saved_space", "space_name", True, "customer_saved_space_editable_noop"),
    ("saved_space", "customer_profile_id", False, "customer_saved_space_owner_denial"),
    ("review", "rating", False, "customer_review_update_denial"),
    ("review", "comment", False, "customer_review_update_denial"),
    ("pending_request", "details", True, "customer_pending_request_editable_noop"),
    (
        "pending_request",
        "lifecycle_state",
        False,
        "customer_request_direct_lifecycle_denial",
    ),
    (
        "pending_request",
        "marketplace_party_id",
        False,
        "customer_request_party_assignment_denial",
    ),
    ("locked_request", "details", False, "customer_locked_request_denial"),
    ("order", "notes", False, "customer_order_update_denial"),
)
SELLER_PROBES: tuple[Probe, ...] = (
    ("offering", "title", True, "seller_offering_editable_noop"),
    ("offering", "marketplace_party_id", False, "seller_offering_owner_denial"),
    ("submitted_line", "quantity", True, "seller_submitted_line_editable_noop"),
    ("submitted_line", "offer_id", False, "seller_line_parent_denial"),
    ("locked_line", "quantity", False, "seller_locked_line_denial"),
    ("order", "notes", True, "seller_order_notes_noop"),
    ("order", "lifecycle_state", False, "seller_order_direct_lifecycle_denial"),
)


def _identifier_filter(
    rows: list[dict[str, object]], *, field: str, check: str, actor: base.Actor
) -> str:
    identifiers = sorted(
        base._secret_identifier(
            row.get(field), check=check, actor=actor
        ).get_secret_value()
        for row in rows
    )
    return f"in.({','.join(identifiers)})"


async def _one_snapshot(
    api: base.PostgrestAcceptanceClient,
    *,
    relation: str,
    fields: tuple[str, ...],
    params: Mapping[str, str],
    session: base.PasswordSession,
    check: str,
    actor: base.Actor,
) -> base.RecordSnapshot:
    """Read at most one page and snapshot the first row, or fail safely."""

    query = dict(params)
    query["limit"] = str(MAX_ACCEPTANCE_ROWS)
    rows = await base._read_rows(
        api,
        relation=relation,
        fields=fields,
        params=query,
        session=session,
        check=check,
        actor=actor,
    )
    if not rows:
        raise base.AcceptanceFailure(
            check=check,
            actor=actor,
            classification="fixture_precondition_not_met",
        )
    return base._snapshot(
        rows[0],
        relation=relation,
        fields=fields,
        check=check,
        actor=actor,
    )


async def _read_link_row(
    api: base.PostgrestAcceptanceClient,
    *,
    relation: str,
    fields: tuple[str, ...],
    params: Mapping[str, str],
    session: base.PasswordSession,
    check: str,
    actor: base.Actor,
) -> LinkRow:
    query = dict(params)
    query["limit"] = str(MAX_ACCEPTANCE_ROWS)
    rows = await base._read_rows(
        api,
        relation=relation,
        fields=fields,
        params=query,
        session=session,
        check=check,
        actor=actor,
    )
    if not rows or set(rows[0]) != set(fields):
        raise base.AcceptanceFailure(
            check=check,
            actor=actor,
            classification="fixture_precondition_not_met",
        )
    values = json.loads(json.dumps(rows[0]))
    key = {
        column: base._secret_identifier(values[column], check=check, actor=actor)
        for column in fields
        if column.endswith("_id")
    }
    return LinkRow(relation=relation, fields=fields, key=key, values=values)


async def _read_link_snapshot(
    api: base.PostgrestAcceptanceClient,
    *,
    expected: LinkRow,
    session: base.PasswordSession,
    check: str,
    actor: base.Actor,
) -> Mapping[str, object]:
    params = {
        column: f"eq.{identifier.get_secret_value()}"
        for column, identifier in expected.key.items()
    }
    params["limit"] = "2"
    rows = await base._read_rows(
        api,
        relation=expected.relation,
        fields=expected.fields,
        params=params,
        session=session,
        check=check,
        actor=actor,
    )
    if len(rows) != 1 or set(rows[0]) != set(expected.fields):
        raise base.AcceptanceFailure(
            check=check,
            actor=actor,
            classification="fixture_changed",
        )
    return json.loads(json.dumps(rows[0]))


async def probe_link_noop_patch_denied(
    api: base.PostgrestAcceptanceClient,
    *,
    session: base.PasswordSession,
    actor: Literal["customer", "seller"],
    expected: LinkRow,
    column: str,
    check: str,
) -> None:
    """Read/PATCH/read a composite-key row and require the PATCH to be denied."""

    before = await _read_link_snapshot(
        api, expected=expected, session=session, check=check, actor=actor
    )
    if before != expected.values or column not in expected.fields:
        raise base.AcceptanceFailure(
            check=check,
            actor=actor,
            classification="fixture_changed",
        )
    params = {
        key_column: f"eq.{identifier.get_secret_value()}"
        for key_column, identifier in expected.key.items()
    }
    params["select"] = ",".join(expected.fields)
    patch_failure: base.AcceptanceFailure | None = None
    try:
        response = await api.patch_relation(
            expected.relation,
            params=params,
            session=session,
            body={column: before[column]},
            check=check,
            actor=actor,
        )
        if response.status_code in base.SAFE_PERMISSION_STATUSES:
            pass
        elif response.status_code == httpx.codes.OK:
            rows = base._row_list(response, check=check, actor=actor)
            if rows or base._affected_count(response) != 0:
                raise base.AcceptanceFailure(
                    check=check,
                    actor=actor,
                    classification="forbidden_write_succeeded",
                    http_status=response.status_code,
                )
        else:
            raise base.AcceptanceFailure(
                check=check,
                actor=actor,
                classification="unexpected_permission_response",
                http_status=response.status_code,
            )
    except base.AcceptanceFailure as failure:
        patch_failure = failure

    try:
        after = await _read_link_snapshot(
            api, expected=expected, session=session, check=check, actor=actor
        )
    except base.AcceptanceFailure:
        raise base.AcceptanceFailure(
            check=check,
            actor=actor,
            classification="post_patch_verification_failed",
        ) from None
    if after != before:
        raise base.AcceptanceFailure(
            check=check,
            actor=actor,
            classification="business_values_changed",
        )
    if patch_failure is not None:
        raise patch_failure
    base.report_result(check=check, actor=actor, status="passed")


async def verify_party_column_boundary(
    api: base.PostgrestAcceptanceClient,
    *,
    customer_session: base.PasswordSession,
) -> None:
    """Prove marketplace_party column grants for anonymous and signed-in reads."""

    for session, actor, hidden_columns in (
        (None, "anonymous", (PARTY_HIDDEN_COLUMN, "state_reason")),
        (customer_session, "customer", (PARTY_HIDDEN_COLUMN,)),
    ):
        for hidden in hidden_columns:
            response = await api.get_relation(
                "marketplace_party",
                params={"select": hidden, "limit": "1"},
                session=session,
                check="party_hidden_column_denial",
                actor=actor,
            )
            if response.status_code not in base.SAFE_PERMISSION_STATUSES:
                raise base.AcceptanceFailure(
                    check="party_hidden_column_denial",
                    actor=actor,
                    classification="private_column_exposed",
                    http_status=response.status_code,
                )

    public_rows = await base._read_rows(
        api,
        relation="marketplace_party",
        fields=PARTY_PUBLIC_FIELDS,
        params={"limit": str(MAX_ACCEPTANCE_ROWS)},
        session=None,
        check="party_public_safe_read",
        actor="anonymous",
    )
    if not public_rows:
        raise base.AcceptanceFailure(
            check="party_public_safe_read",
            actor="anonymous",
            classification="fixture_precondition_not_met",
        )
    for row in public_rows:
        if set(row) != set(PARTY_PUBLIC_FIELDS):
            raise base.AcceptanceFailure(
                check="party_public_safe_read",
                actor="anonymous",
                classification="malformed_response",
            )
        if row.get("approval_state") != "approved":
            raise base.AcceptanceFailure(
                check="party_public_safe_read",
                actor="anonymous",
                classification="unapproved_party_exposed",
            )
        base._secret_identifier(
            row.get("id"), check="party_public_safe_read", actor="anonymous"
        )

    signed_in_rows = await base._read_rows(
        api,
        relation="marketplace_party",
        fields=PARTY_AUTHENTICATED_FIELDS,
        params={"limit": "1"},
        session=customer_session,
        check="party_authenticated_read",
        actor="customer",
    )
    if any(set(row) != set(PARTY_AUTHENTICATED_FIELDS) for row in signed_in_rows):
        raise base.AcceptanceFailure(
            check="party_authenticated_read",
            actor="customer",
            classification="malformed_response",
        )
    base.report_result(
        check="party_column_boundary",
        actor="anonymous",
        status="passed",
    )


async def discover_customer_fixtures(
    api: base.PostgrestAcceptanceClient,
    *,
    customer_session: base.PasswordSession,
    customer_profile_id: SecretStr,
) -> CustomerFixtures:
    """Read and validate every customer fixture before any PATCH begins."""

    check = "customer_fixture_discovery"
    actor: Literal["customer"] = "customer"
    owner = f"eq.{customer_profile_id.get_secret_value()}"

    async def owned(
        relation: str, fields: tuple[str, ...], **extra: str
    ) -> base.RecordSnapshot:
        params = {"customer_profile_id": owner, **extra}
        snapshot = await _one_snapshot(
            api,
            relation=relation,
            fields=fields,
            params=params,
            session=customer_session,
            check=check,
            actor=actor,
        )
        if (
            snapshot.values.get("customer_profile_id")
            != customer_profile_id.get_secret_value()
        ):
            raise base.AcceptanceFailure(
                check=check,
                actor=actor,
                classification="fixture_ownership_mismatch",
            )
        return snapshot

    address = await owned("address", ADDRESS_FIELDS)
    cart = await owned("cart", CART_FIELDS)
    cart_line = await _one_snapshot(
        api,
        relation="cart_line",
        fields=CART_LINE_FIELDS,
        params={"cart_id": f"eq.{cart.identifier.get_secret_value()}"},
        session=customer_session,
        check=check,
        actor=actor,
    )
    saved_space = await owned("saved_space", SAVED_SPACE_FIELDS)
    review = await owned("review", REVIEW_FIELDS)
    pending_request = await owned(
        "service_request",
        SERVICE_REQUEST_FIELDS,
        lifecycle_state=f"eq.{PENDING_SERVICE_STATE}",
    )
    locked_request = await owned(
        "service_request",
        SERVICE_REQUEST_FIELDS,
        lifecycle_state=f"in.({','.join(LOCKED_SERVICE_STATES)})",
    )
    if pending_request.values.get("marketplace_party_id") is not None:
        raise base.AcceptanceFailure(
            check=check,
            actor=actor,
            classification="fixture_precondition_not_met",
        )
    order = await owned("purchase_order", PURCHASE_ORDER_FIELDS)

    design_rows = await base._read_rows(
        api,
        relation="design",
        fields=("id",),
        params={"limit": str(MAX_ACCEPTANCE_ROWS)},
        session=customer_session,
        check=check,
        actor=actor,
    )
    if not design_rows:
        raise base.AcceptanceFailure(
            check=check,
            actor=actor,
            classification="fixture_precondition_not_met",
        )
    design_reference = await _read_link_row(
        api,
        relation="design_product_reference",
        fields=DESIGN_PRODUCT_REFERENCE_FIELDS,
        params={
            "design_id": _identifier_filter(
                design_rows, field="id", check=check, actor=actor
            )
        },
        session=customer_session,
        check=check,
        actor=actor,
    )

    request_rows = await base._read_rows(
        api,
        relation="furnishing_request",
        fields=("id",),
        params={"customer_profile_id": owner, "limit": str(MAX_ACCEPTANCE_ROWS)},
        session=customer_session,
        check=check,
        actor=actor,
    )
    if not request_rows:
        raise base.AcceptanceFailure(
            check=check,
            actor=actor,
            classification="fixture_precondition_not_met",
        )
    request_design_version = await _read_link_row(
        api,
        relation="furnishing_request_design_version",
        fields=FURNISHING_REQUEST_DESIGN_VERSION_FIELDS,
        params={
            "furnishing_request_id": _identifier_filter(
                request_rows, field="id", check=check, actor=actor
            )
        },
        session=customer_session,
        check=check,
        actor=actor,
    )
    return CustomerFixtures(
        address=address,
        cart=cart,
        cart_line=cart_line,
        saved_space=saved_space,
        review=review,
        pending_request=pending_request,
        locked_request=locked_request,
        order=order,
        design_reference=design_reference,
        request_design_version=request_design_version,
    )


async def discover_seller_fixtures(
    api: base.PostgrestAcceptanceClient,
    *,
    seller_session: base.PasswordSession,
    seller_party_id: SecretStr,
) -> SellerFixtures:
    """Read and validate every seller fixture before any PATCH begins."""

    check = "seller_fixture_discovery"
    actor: Literal["seller"] = "seller"
    party = f"eq.{seller_party_id.get_secret_value()}"

    offering = await _one_snapshot(
        api,
        relation="custom_offering",
        fields=CUSTOM_OFFERING_FIELDS,
        params={"marketplace_party_id": party},
        session=seller_session,
        check=check,
        actor=actor,
    )
    order = await _one_snapshot(
        api,
        relation="purchase_order",
        fields=PURCHASE_ORDER_FIELDS,
        params={"marketplace_party_id": party},
        session=seller_session,
        check=check,
        actor=actor,
    )
    for snapshot in (offering, order):
        if (
            snapshot.values.get("marketplace_party_id")
            != seller_party_id.get_secret_value()
        ):
            raise base.AcceptanceFailure(
                check=check,
                actor=actor,
                classification="fixture_ownership_mismatch",
            )

    async def line_for(state_filter: str) -> base.RecordSnapshot:
        offers = await base._read_rows(
            api,
            relation="offer",
            fields=("id", "lifecycle_state"),
            params={
                "marketplace_party_id": party,
                "lifecycle_state": state_filter,
                "limit": str(MAX_ACCEPTANCE_ROWS),
            },
            session=seller_session,
            check=check,
            actor=actor,
        )
        if not offers:
            raise base.AcceptanceFailure(
                check=check,
                actor=actor,
                classification="fixture_precondition_not_met",
            )
        return await _one_snapshot(
            api,
            relation="offer_line_item",
            fields=OFFER_LINE_ITEM_FIELDS,
            params={
                "offer_id": _identifier_filter(
                    offers, field="id", check=check, actor=actor
                )
            },
            session=seller_session,
            check=check,
            actor=actor,
        )

    submitted_line = await line_for(f"eq.{SUBMITTED_OFFER_STATE}")
    locked_line = await line_for(f"neq.{SUBMITTED_OFFER_STATE}")
    capability = await _read_link_row(
        api,
        relation="party_capability",
        fields=PARTY_CAPABILITY_FIELDS,
        params={"marketplace_party_id": party},
        session=seller_session,
        check=check,
        actor=actor,
    )
    return SellerFixtures(
        offering=offering,
        submitted_line=submitted_line,
        locked_line=locked_line,
        order=order,
        capability=capability,
    )


async def verify_customer_write_boundaries(
    api: base.PostgrestAcceptanceClient,
    *,
    customer_session: base.PasswordSession,
    fixtures: CustomerFixtures,
) -> None:
    for attribute, column, allowed, check in CUSTOMER_PROBES:
        await base.probe_noop_patch(
            api,
            session=customer_session,
            actor="customer",
            expected=getattr(fixtures, attribute),
            column=column,
            allowed=allowed,
            check=check,
        )
    await probe_link_noop_patch_denied(
        api,
        session=customer_session,
        actor="customer",
        expected=fixtures.design_reference,
        column="product_id",
        check="customer_design_reference_update_denial",
    )
    await probe_link_noop_patch_denied(
        api,
        session=customer_session,
        actor="customer",
        expected=fixtures.request_design_version,
        column="design_version_id",
        check="customer_request_design_version_update_denial",
    )
    base.report_result(
        check="customer_write_boundaries",
        actor="customer",
        status="passed",
    )


async def verify_seller_write_boundaries(
    api: base.PostgrestAcceptanceClient,
    *,
    seller_session: base.PasswordSession,
    fixtures: SellerFixtures,
) -> None:
    for attribute, column, allowed, check in SELLER_PROBES:
        await base.probe_noop_patch(
            api,
            session=seller_session,
            actor="seller",
            expected=getattr(fixtures, attribute),
            column=column,
            allowed=allowed,
            check=check,
        )
    await probe_link_noop_patch_denied(
        api,
        session=seller_session,
        actor="seller",
        expected=fixtures.capability,
        column="declared_at",
        check="seller_capability_update_denial",
    )
    base.report_result(
        check="seller_write_boundaries",
        actor="seller",
        status="passed",
    )


async def run_acceptance_checks(
    *,
    settings: Settings,
    customer_session: base.PasswordSession,
    seller_session: base.PasswordSession,
    client: httpx.AsyncClient,
) -> None:
    api = base.PostgrestAcceptanceClient(client=client, settings=settings)
    await verify_party_column_boundary(api, customer_session=customer_session)
    customer_profile_id = base._secret_identifier(
        await base._rpc_value(
            api,
            function_name="current_customer_profile_id",
            session=customer_session,
            actor="customer",
            check="customer_profile_helper",
        ),
        check="customer_profile_helper",
        actor="customer",
    )
    seller_party_id = await base.verify_seller_helpers(api, session=seller_session)
    customer_fixtures = await discover_customer_fixtures(
        api,
        customer_session=customer_session,
        customer_profile_id=customer_profile_id,
    )
    seller_fixtures = await discover_seller_fixtures(
        api,
        seller_session=seller_session,
        seller_party_id=seller_party_id,
    )
    await verify_customer_write_boundaries(
        api,
        customer_session=customer_session,
        fixtures=customer_fixtures,
    )
    await verify_seller_write_boundaries(
        api,
        seller_session=seller_session,
        fixtures=seller_fixtures,
    )
    await base.verify_financial_view_scope(
        api,
        session=customer_session,
        actor="customer",
    )
    await base.verify_financial_view_scope(
        api,
        session=seller_session,
        actor="seller",
    )


async def async_main() -> None:
    base.reject_forbidden_secret_configuration()
    secrets = base.collect_interactive_secrets()
    try:
        settings = load_settings()
    except RuntimeError:
        raise base.AcceptanceFailure(
            check="configuration",
            classification="invalid_configuration",
        ) from None

    logging.getLogger("httpx").disabled = True
    logging.getLogger("httpcore").disabled = True
    async with httpx.AsyncClient() as auth_client:
        customer_session = await base.sign_in(
            client=auth_client,
            settings=settings,
            actor="customer",
            email=base.CUSTOMER_EMAIL,
            password=secrets.customer_password,
        )
        base.report_result(
            check="password_authentication",
            actor="customer",
            status="passed",
        )
        seller_session = await base.sign_in(
            client=auth_client,
            settings=settings,
            actor="seller",
            email=base.SELLER_EMAIL,
            password=secrets.seller_password,
        )
        base.report_result(
            check="password_authentication",
            actor="seller",
            status="passed",
        )
    del secrets

    async with httpx.AsyncClient() as acceptance_client:
        await run_acceptance_checks(
            settings=settings,
            customer_session=customer_session,
            seller_session=seller_session,
            client=acceptance_client,
        )
    del customer_session
    del seller_session


def main() -> int:
    try:
        asyncio.run(async_main())
    except base.AcceptanceFailure as failure:
        base.report_result(
            check=failure.check,
            actor=failure.actor,
            status="failed",
            classification=failure.classification,
            http_status=failure.http_status,
        )
        return 1
    except KeyboardInterrupt:
        base.report_result(
            check="credential_input",
            actor="runner",
            status="failed",
            classification="credential_input_cancelled",
        )
        return 1
    except Exception:
        base.report_result(
            check="live_phase_3_2d_acceptance",
            actor="runner",
            status="failed",
            classification="unexpected_internal_error",
        )
        return 1
    return 0


def _exit() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _exit()
