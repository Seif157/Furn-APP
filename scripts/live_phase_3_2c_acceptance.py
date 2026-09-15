"""Secure live acceptance checks for the review-only Phase 3.2C proposal.

This utility is intentionally not part of the application. It uses the safe
interactive/authentication and no-op PATCH primitives from Phase 3.2B and must
only be run after a reviewed migration is applied to a fake-data test branch.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import NoReturn

import httpx
from pydantic import SecretStr

from app.config import Settings, load_settings
from scripts import live_rls_acceptance as base

SAFE_REVIEW_FIELDS = (
    "id",
    "target_kind",
    "target_product_id",
    "target_marketplace_party_id",
    "rating",
    "comment",
    "created_at",
)
RAW_REVIEW_FIELDS = (
    "id",
    "customer_profile_id",
    "target_kind",
    "target_product_id",
    "target_marketplace_party_id",
    "target_service_request_id",
    "rating",
    "comment",
    "created_at",
)
FURNISHING_REQUEST_FIELDS = (
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
FURNISHING_EDITABLE_PROBE_COLUMN = "coarse_location"
LOCKED_FURNISHING_STATES = ("accepted", "withdrawn", "closed")
MAX_ACCEPTANCE_ROWS = 100


@dataclass(frozen=True, slots=True)
class Phase32CFixtures:
    """All private values required before the first no-op PATCH."""

    editable_requests: tuple[base.RecordSnapshot, ...]
    locked_requests: tuple[base.RecordSnapshot, ...]


def _uuid_set(
    rows: list[dict[str, object]],
    *,
    field: str,
    check: str,
    actor: base.Actor,
) -> set[str]:
    identifiers: set[str] = set()
    for row in rows:
        identifiers.add(
            base._secret_identifier(
                row.get(field),
                check=check,
                actor=actor,
            ).get_secret_value()
        )
    return identifiers


async def verify_anonymous_review_boundary(
    api: base.PostgrestAcceptanceClient,
) -> None:
    """Prove exact safe-column access and cross-check anonymous RLS scope."""

    helper_response = await api.get_rpc(
        "current_customer_profile_id",
        session=None,
        check="anonymous_customer_helper_denial",
        actor="anonymous",
    )
    if helper_response.status_code not in base.SAFE_PERMISSION_STATUSES:
        raise base.AcceptanceFailure(
            check="anonymous_customer_helper_denial",
            actor="anonymous",
            classification="restricted_helper_executable",
            http_status=helper_response.status_code,
        )
    base.report_result(
        check="anonymous_customer_helper_denial",
        actor="anonymous",
        status="passed",
    )

    for sensitive_column in (
        "customer_profile_id",
        "target_service_request_id",
    ):
        response = await api.get_relation(
            "review",
            params={"select": sensitive_column, "limit": "1"},
            session=None,
            check="anonymous_sensitive_review_column_denial",
            actor="anonymous",
        )
        if response.status_code not in base.SAFE_PERMISSION_STATUSES:
            raise base.AcceptanceFailure(
                check="anonymous_sensitive_review_column_denial",
                actor="anonymous",
                classification="private_column_exposed",
                http_status=response.status_code,
            )

    rows = await base._read_rows(
        api,
        relation="review",
        fields=SAFE_REVIEW_FIELDS,
        params={"limit": str(MAX_ACCEPTANCE_ROWS)},
        session=None,
        check="anonymous_safe_review_read",
        actor="anonymous",
    )
    product_ids: set[str] = set()
    party_ids: set[str] = set()
    for row in rows:
        if set(row) != set(SAFE_REVIEW_FIELDS):
            raise base.AcceptanceFailure(
                check="anonymous_safe_review_read",
                actor="anonymous",
                classification="malformed_response",
            )
        target_kind = row.get("target_kind")
        if row.get("target_service_request_id") is not None:
            # This field is not selected and its appearance is always a leak.
            raise base.AcceptanceFailure(
                check="anonymous_safe_review_read",
                actor="anonymous",
                classification="private_column_exposed",
            )
        if target_kind == "product":
            if (
                row.get("target_marketplace_party_id") is not None
                or row.get("target_product_id") is None
            ):
                raise base.AcceptanceFailure(
                    check="anonymous_safe_review_read",
                    actor="anonymous",
                    classification="invalid_anonymous_review_target",
                )
            product_ids |= _uuid_set(
                [row],
                field="target_product_id",
                check="anonymous_safe_review_read",
                actor="anonymous",
            )
        elif target_kind == "marketplace_party":
            if (
                row.get("target_product_id") is not None
                or row.get("target_marketplace_party_id") is None
            ):
                raise base.AcceptanceFailure(
                    check="anonymous_safe_review_read",
                    actor="anonymous",
                    classification="invalid_anonymous_review_target",
                )
            party_ids |= _uuid_set(
                [row],
                field="target_marketplace_party_id",
                check="anonymous_safe_review_read",
                actor="anonymous",
            )
        else:
            raise base.AcceptanceFailure(
                check="anonymous_safe_review_read",
                actor="anonymous",
                classification="service_review_exposed",
            )

    if not product_ids or not party_ids:
        raise base.AcceptanceFailure(
            check="anonymous_safe_review_read",
            actor="anonymous",
            classification="fixture_precondition_not_met",
        )

    product_params = dict(base.ELIGIBLE_CATALOGUE_PARAMS)
    product_params["id"] = f"in.({','.join(sorted(product_ids))})"
    product_params["limit"] = str(MAX_ACCEPTANCE_ROWS)
    product_response = await api.get_relation(
        "product",
        params=product_params,
        session=None,
        check="public_product_review_eligibility",
        actor="anonymous",
    )
    eligible_products = _uuid_set(
        base._row_list(
            product_response,
            check="public_product_review_eligibility",
            actor="anonymous",
        ),
        field="id",
        check="public_product_review_eligibility",
        actor="anonymous",
    )
    if eligible_products != product_ids:
        raise base.AcceptanceFailure(
            check="public_product_review_eligibility",
            actor="anonymous",
            classification="review_eligibility_violation",
        )

    party_rows = await base._read_rows(
        api,
        relation="marketplace_party",
        fields=("id",),
        params={
            "id": f"in.({','.join(sorted(party_ids))})",
            "approval_state": "eq.approved",
            "limit": str(MAX_ACCEPTANCE_ROWS),
        },
        session=None,
        check="public_party_review_eligibility",
        actor="anonymous",
    )
    approved_parties = _uuid_set(
        party_rows,
        field="id",
        check="public_party_review_eligibility",
        actor="anonymous",
    )
    if approved_parties != party_ids:
        raise base.AcceptanceFailure(
            check="public_party_review_eligibility",
            actor="anonymous",
            classification="review_eligibility_violation",
        )

    service_rows = await base._read_rows(
        api,
        relation="review",
        fields=SAFE_REVIEW_FIELDS,
        params={"target_kind": "eq.service_request", "limit": "1"},
        session=None,
        check="public_service_review_denial",
        actor="anonymous",
    )
    if service_rows:
        raise base.AcceptanceFailure(
            check="public_service_review_denial",
            actor="anonymous",
            classification="service_review_exposed",
        )
    base.report_result(
        check="anonymous_safe_review_read",
        actor="anonymous",
        status="passed",
    )


async def verify_authenticated_review_owner(
    api: base.PostgrestAcceptanceClient,
    *,
    customer_session: base.PasswordSession,
) -> SecretStr:
    """Require an authenticated customer to see at least one own raw review."""

    profile_id = await base._rpc_value(
        api,
        function_name="current_customer_profile_id",
        session=customer_session,
        check="customer_profile_helper",
        actor="customer",
    )
    profile_id = base._secret_identifier(
        profile_id,
        check="customer_profile_helper",
        actor="customer",
    )
    rows = await base._read_rows(
        api,
        relation="review",
        fields=RAW_REVIEW_FIELDS,
        params={
            "customer_profile_id": f"eq.{profile_id.get_secret_value()}",
            "limit": "1",
        },
        session=customer_session,
        check="customer_own_raw_review",
        actor="customer",
    )
    if not rows:
        raise base.AcceptanceFailure(
            check="customer_own_raw_review",
            actor="customer",
            classification="fixture_precondition_not_met",
        )
    if any(
        set(row) != set(RAW_REVIEW_FIELDS)
        or row.get("customer_profile_id") != profile_id.get_secret_value()
        for row in rows
    ):
        raise base.AcceptanceFailure(
            check="customer_own_raw_review",
            actor="customer",
            classification="raw_review_scope_violation",
        )
    base.report_result(
        check="customer_own_raw_review",
        actor="customer",
        status="passed",
    )
    return profile_id


async def verify_public_service_directory(
    api: base.PostgrestAcceptanceClient,
) -> None:
    """Cross-check active services and approved-party public capabilities."""

    service_rows = await base._read_rows(
        api,
        relation="service_type",
        fields=("id", "is_active"),
        params={"limit": str(MAX_ACCEPTANCE_ROWS)},
        session=None,
        check="public_active_service_types",
        actor="anonymous",
    )
    if not service_rows or any(
        row.get("is_active") is not True for row in service_rows
    ):
        raise base.AcceptanceFailure(
            check="public_active_service_types",
            actor="anonymous",
            classification="service_directory_scope_violation",
        )
    _uuid_set(
        service_rows,
        field="id",
        check="public_active_service_types",
        actor="anonymous",
    )

    capability_rows = await base._read_rows(
        api,
        relation="party_capability",
        fields=("marketplace_party_id", "service_type_id"),
        params={"limit": str(MAX_ACCEPTANCE_ROWS)},
        session=None,
        check="public_approved_party_capabilities",
        actor="anonymous",
    )
    if not capability_rows:
        raise base.AcceptanceFailure(
            check="public_approved_party_capabilities",
            actor="anonymous",
            classification="fixture_precondition_not_met",
        )
    party_ids = _uuid_set(
        capability_rows,
        field="marketplace_party_id",
        check="public_approved_party_capabilities",
        actor="anonymous",
    )
    capability_service_ids = _uuid_set(
        capability_rows,
        field="service_type_id",
        check="public_approved_party_capabilities",
        actor="anonymous",
    )
    eligible_service_rows = await base._read_rows(
        api,
        relation="service_type",
        fields=("id",),
        params={
            "id": f"in.({','.join(sorted(capability_service_ids))})",
            "is_active": "eq.true",
            "limit": str(MAX_ACCEPTANCE_ROWS),
        },
        session=None,
        check="public_approved_party_capabilities",
        actor="anonymous",
    )
    if (
        _uuid_set(
            eligible_service_rows,
            field="id",
            check="public_approved_party_capabilities",
            actor="anonymous",
        )
        != capability_service_ids
    ):
        raise base.AcceptanceFailure(
            check="public_approved_party_capabilities",
            actor="anonymous",
            classification="service_directory_scope_violation",
        )
    approved_rows = await base._read_rows(
        api,
        relation="marketplace_party",
        fields=("id",),
        params={
            "id": f"in.({','.join(sorted(party_ids))})",
            "approval_state": "eq.approved",
            "limit": str(MAX_ACCEPTANCE_ROWS),
        },
        session=None,
        check="public_approved_party_capabilities",
        actor="anonymous",
    )
    if (
        _uuid_set(
            approved_rows,
            field="id",
            check="public_approved_party_capabilities",
            actor="anonymous",
        )
        != party_ids
    ):
        raise base.AcceptanceFailure(
            check="public_approved_party_capabilities",
            actor="anonymous",
            classification="service_directory_scope_violation",
        )
    base.report_result(
        check="public_service_directory",
        actor="anonymous",
        status="passed",
    )


async def verify_seller_own_capability(
    api: base.PostgrestAcceptanceClient,
    *,
    seller_session: base.PasswordSession,
    seller_party_id: SecretStr,
) -> None:
    rows = await base._read_rows(
        api,
        relation="party_capability",
        fields=("marketplace_party_id", "service_type_id"),
        params={
            "marketplace_party_id": f"eq.{seller_party_id.get_secret_value()}",
            "limit": str(MAX_ACCEPTANCE_ROWS),
        },
        session=seller_session,
        check="seller_own_capability_read",
        actor="seller",
    )
    if not rows or any(
        row.get("marketplace_party_id") != seller_party_id.get_secret_value()
        for row in rows
    ):
        raise base.AcceptanceFailure(
            check="seller_own_capability_read",
            actor="seller",
            classification="fixture_precondition_not_met",
        )
    seller_only_found = False
    for row in rows:
        service_type_id = base._secret_identifier(
            row.get("service_type_id"),
            check="seller_own_capability_read",
            actor="seller",
        )
        anonymous_rows = await base._read_rows(
            api,
            relation="party_capability",
            fields=("marketplace_party_id", "service_type_id"),
            params={
                "marketplace_party_id": f"eq.{seller_party_id.get_secret_value()}",
                "service_type_id": f"eq.{service_type_id.get_secret_value()}",
                "limit": "1",
            },
            session=None,
            check="seller_own_capability_read",
            actor="anonymous",
        )
        if not anonymous_rows:
            seller_only_found = True
            break
    if not seller_only_found:
        raise base.AcceptanceFailure(
            check="seller_own_capability_read",
            actor="seller",
            classification="fixture_precondition_not_met",
        )
    base.report_result(
        check="seller_own_capability_read",
        actor="seller",
        status="passed",
    )


async def discover_furnishing_fixtures(
    api: base.PostgrestAcceptanceClient,
    *,
    customer_session: base.PasswordSession,
    customer_profile_id: SecretStr,
) -> Phase32CFixtures:
    """Read and validate every furnishing fixture before any PATCH begins."""

    rows = await base._read_rows(
        api,
        relation="furnishing_request",
        fields=FURNISHING_REQUEST_FIELDS,
        params={
            "customer_profile_id": f"eq.{customer_profile_id.get_secret_value()}",
            "lifecycle_state": "in.(draft,open,accepted,withdrawn,closed)",
            "limit": str(MAX_ACCEPTANCE_ROWS),
        },
        session=customer_session,
        check="furnishing_fixture_discovery",
        actor="customer",
    )
    by_state: dict[str, base.RecordSnapshot] = {}
    for row in rows:
        if row.get("customer_profile_id") != customer_profile_id.get_secret_value():
            raise base.AcceptanceFailure(
                check="furnishing_fixture_discovery",
                actor="customer",
                classification="fixture_ownership_mismatch",
            )
        state = row.get("lifecycle_state")
        if isinstance(state, str) and state not in by_state:
            by_state[state] = base._snapshot(
                row,
                relation="furnishing_request",
                fields=FURNISHING_REQUEST_FIELDS,
                check="furnishing_fixture_discovery",
                actor="customer",
            )
    editable = tuple(by_state.get(state) for state in ("draft", "open"))
    locked = tuple(by_state.get(state) for state in LOCKED_FURNISHING_STATES)
    if any(snapshot is None for snapshot in editable) or any(
        snapshot is None for snapshot in locked
    ):
        raise base.AcceptanceFailure(
            check="furnishing_fixture_discovery",
            actor="customer",
            classification="fixture_precondition_not_met",
        )
    return Phase32CFixtures(
        editable_requests=tuple(
            snapshot for snapshot in editable if snapshot is not None
        ),
        locked_requests=tuple(snapshot for snapshot in locked if snapshot is not None),
    )


async def verify_furnishing_update_boundaries(
    api: base.PostgrestAcceptanceClient,
    *,
    customer_session: base.PasswordSession,
    fixtures: Phase32CFixtures,
) -> None:
    for snapshot in fixtures.editable_requests:
        await base.probe_noop_patch(
            api,
            session=customer_session,
            actor="customer",
            expected=snapshot,
            column="lifecycle_state",
            allowed=False,
            check="customer_direct_lifecycle_denial",
        )
        await base.probe_noop_patch(
            api,
            session=customer_session,
            actor="customer",
            expected=snapshot,
            column=FURNISHING_EDITABLE_PROBE_COLUMN,
            allowed=True,
            check="customer_editable_furnishing_noop",
        )
    for snapshot in fixtures.locked_requests:
        await base.probe_noop_patch(
            api,
            session=customer_session,
            actor="customer",
            expected=snapshot,
            column=FURNISHING_EDITABLE_PROBE_COLUMN,
            allowed=False,
            check="customer_locked_furnishing_denial",
        )
    base.report_result(
        check="furnishing_update_boundaries",
        actor="customer",
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
    await verify_anonymous_review_boundary(api)
    customer_profile_id = await verify_authenticated_review_owner(
        api,
        customer_session=customer_session,
    )
    await verify_public_service_directory(api)
    seller_party_id = await base.verify_seller_helpers(
        api,
        session=seller_session,
    )
    await verify_seller_own_capability(
        api,
        seller_session=seller_session,
        seller_party_id=seller_party_id,
    )
    fixtures = await discover_furnishing_fixtures(
        api,
        customer_session=customer_session,
        customer_profile_id=customer_profile_id,
    )
    await verify_furnishing_update_boundaries(
        api,
        customer_session=customer_session,
        fixtures=fixtures,
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
            check="live_phase_3_2c_acceptance",
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
