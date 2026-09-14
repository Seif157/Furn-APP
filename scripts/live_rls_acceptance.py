"""Secure staged RLS acceptance checks for a fake-data Supabase branch."""

import asyncio
import getpass
import json
import logging
import os
import re
import sys
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, NoReturn
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.config import Settings, load_settings

CUSTOMER_EMAIL = "customer1@furnihub.test"
SELLER_EMAIL = "seller1@furnihub.test"
TEST_BRANCH_CONFIRMATION = "FAKE-DATA TESTING BRANCH"
MAX_FIXTURE_ROWS = 100

Actor = Literal["anonymous", "customer", "seller", "runner"]

FORBIDDEN_SECRET_ENVIRONMENT_NAMES = frozenset(
    {
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_SECRET_KEY",
        "SUPABASE_JWT_SECRET",
    }
)
PUBLIC_CATALOGUE_READS: dict[str, tuple[str, ...] | None] = {
    "category": ("id",),
    "custom_offering": ("id",),
    "marketplace_party": ("id",),
    # The acceptance check does not assume an independent surrogate key here.
    "party_capability": None,
    "product": ("id",),
    "product_3d_model": ("id",),
    "product_color": ("id",),
    "product_image": ("id",),
    # This assignment table has a composite key and deliberately has no `id`.
    "product_enrichment_assignment": ("product_id", "attribute_id"),
    "product_enrichment_attribute": ("id",),
    "review": ("id",),
    "service_type": ("id",),
}
PRIVATE_ANONYMOUS_RELATIONS = (
    "address",
    "admin_user",
    "cart",
    "cart_line",
    "commission",
    "commission_reversal",
    "customer_profile",
    "design",
    "design_product_reference",
    "design_version",
    "furnishing_request",
    "furnishing_request_design_version",
    "offer",
    "offer_line_item",
    "order_line_item",
    "payment",
    "platform_config",
    "purchase_order",
    "refund",
    "saved_space",
    "service_request",
    "settlement",
    "order_financial_position",
)
RESTRICTED_HELPERS = (
    "is_admin",
    "current_marketplace_party_id",
    "current_party_is_approved",
)
PARTY_FIELDS = (
    "id",
    "business_name",
    "business_description",
    "logo_url",
    "coverage_area",
    "approval_state",
    "state_reason",
)
PRODUCT_FIELDS = (
    "id",
    "marketplace_party_id",
    "category_id",
    "name",
    "description",
    "price",
    "discount_price",
    "width_cm",
    "height_cm",
    "depth_cm",
    "weight_kg",
    "materials",
    "lifecycle_state",
    "sku",
)
PRODUCT_COLOR_FIELDS = (
    "id",
    "product_id",
    "color_value",
    "stock_quantity",
    "display_order",
)
ELIGIBLE_CATALOGUE_SELECT = (
    "id,"
    "category:category!product_category_fk!inner(id),"
    "seller:marketplace_party!product_party_fk!inner(id),"
    "colors:product_color!product_color_product_fk!inner(id)"
)
ELIGIBLE_CATALOGUE_PARAMS = {
    "select": ELIGIBLE_CATALOGUE_SELECT,
    "lifecycle_state": "eq.published",
    "seller.approval_state": "eq.approved",
    "category.is_active": "eq.true",
    "colors.stock_quantity": "gt.0",
    "limit": "1",
}
SAFE_PERMISSION_STATUSES = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})
SAFE_LABEL = re.compile(r"[a-z][a-z0-9_]{0,79}")


class PasswordSession(BaseModel):
    """Secret-bearing session data that is excluded from serialization/repr."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    access_token: SecretStr = Field(exclude=True, repr=False)
    refresh_token: SecretStr = Field(exclude=True, repr=False)


class InteractiveSecrets(BaseModel):
    """Passwords collected from a secure terminal and retained only in memory."""

    model_config = ConfigDict(frozen=True, strict=True)

    customer_password: SecretStr = Field(exclude=True, repr=False)
    seller_password: SecretStr = Field(exclude=True, repr=False)


class AcceptanceFailure(Exception):
    """Value-free failure metadata safe to display."""

    def __init__(
        self,
        *,
        check: str,
        actor: Actor = "runner",
        classification: str,
        http_status: int | None = None,
    ) -> None:
        super().__init__(classification)
        self.check = check
        self.actor = actor
        self.classification = classification
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class RecordSnapshot:
    """A private in-memory snapshot used for identity and equality checks."""

    relation: str
    fields: tuple[str, ...]
    identifier: SecretStr = field(repr=False)
    values: Mapping[str, object] = field(repr=False)

    def existing_value(self, column: str) -> object:
        if column not in self.fields:
            raise AcceptanceFailure(
                check="fixture_discovery",
                classification="fixture_precondition_not_met",
            )
        return self.values[column]


@dataclass(frozen=True, slots=True)
class AcceptanceFixtures:
    """All identities and values required before the first PATCH is allowed."""

    seller_party: RecordSnapshot
    own_product: RecordSnapshot
    other_product: RecordSnapshot
    own_child: RecordSnapshot
    other_child: RecordSnapshot


def report_result(
    *,
    check: str,
    actor: Actor,
    status: Literal["passed", "failed"],
    classification: str | None = None,
    http_status: int | None = None,
) -> None:
    """Print only allow-listed labels, role classes, status, and status codes."""

    if SAFE_LABEL.fullmatch(check) is None:
        check = "invalid_check_label"
    if classification is not None and SAFE_LABEL.fullmatch(classification) is None:
        classification = "invalid_failure_classification"
    fields = [f"check={check}", f"actor={actor}", f"status={status}"]
    if http_status is not None:
        fields.append(f"http_status={http_status}")
    if classification is not None:
        fields.append(f"safe_error_classification={classification}")
    print(" ".join(fields), flush=True)


def reject_forbidden_secret_configuration(
    environment: Mapping[str, str] | None = None,
) -> None:
    """Fail without reading values when elevated Supabase secrets are present."""

    names = os.environ if environment is None else environment
    if FORBIDDEN_SECRET_ENVIRONMENT_NAMES & names.keys():
        raise AcceptanceFailure(
            check="configuration",
            classification="forbidden_secret_configuration",
        )


def _secure_password(actor: Literal["customer", "seller"]) -> SecretStr:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            raw_password = getpass.getpass(f"{actor} password: ")
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        raise AcceptanceFailure(
            check="credential_input",
            classification="secure_terminal_required",
        ) from None
    if not raw_password:
        raise AcceptanceFailure(
            check="credential_input",
            classification="credentials_required",
        )
    password = SecretStr(raw_password)
    del raw_password
    return password


def collect_interactive_secrets() -> InteractiveSecrets:
    """Require a TTY, explicit fake-branch confirmation, and two passwords."""

    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise AcceptanceFailure(
            check="credential_input",
            classification="secure_terminal_required",
        )
    try:
        confirmation = input("testing-branch confirmation: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise AcceptanceFailure(
            check="testing_branch_confirmation",
            classification="confirmation_cancelled",
        ) from None
    if confirmation != TEST_BRANCH_CONFIRMATION:
        raise AcceptanceFailure(
            check="testing_branch_confirmation",
            classification="testing_branch_not_confirmed",
        )
    del confirmation
    report_result(
        check="testing_branch_confirmation",
        actor="runner",
        status="passed",
    )

    customer_password = _secure_password("customer")
    report_result(check="customer_credential_input", actor="customer", status="passed")
    seller_password = _secure_password("seller")
    report_result(check="seller_credential_input", actor="seller", status="passed")
    return InteractiveSecrets(
        customer_password=customer_password,
        seller_password=seller_password,
    )


def _request_classification(status_code: int) -> str:
    if status_code == httpx.codes.TOO_MANY_REQUESTS or status_code >= 500:
        return "upstream_unavailable"
    if status_code in SAFE_PERMISSION_STATUSES:
        return "permission_denied"
    return "unexpected_http_status"


async def sign_in(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    actor: Literal["customer", "seller"],
    email: str,
    password: SecretStr,
) -> PasswordSession:
    """Use the sole required POST for password authentication, never data writes."""

    endpoint = (
        f"{str(settings.supabase_url).rstrip('/')}/auth/v1/token?grant_type=password"
    )
    try:
        response = await client.post(
            endpoint,
            headers={
                "Accept": "application/json",
                "apikey": settings.supabase_publishable_key.get_secret_value(),
            },
            json={"email": email, "password": password.get_secret_value()},
            timeout=settings.supabase_auth_timeout_seconds,
        )
    except (httpx.TimeoutException, httpx.RequestError):
        raise AcceptanceFailure(
            check="password_authentication",
            actor=actor,
            classification="authentication_service_unavailable",
        ) from None
    if response.status_code != httpx.codes.OK:
        raise AcceptanceFailure(
            check="password_authentication",
            actor=actor,
            classification=_request_classification(response.status_code),
            http_status=response.status_code,
        )
    try:
        session = PasswordSession.model_validate_json(response.content, strict=True)
    except ValidationError:
        raise AcceptanceFailure(
            check="password_authentication",
            actor=actor,
            classification="invalid_authentication_response",
            http_status=response.status_code,
        ) from None
    if not all(
        (
            session.access_token.get_secret_value(),
            session.refresh_token.get_secret_value(),
        )
    ):
        raise AcceptanceFailure(
            check="password_authentication",
            actor=actor,
            classification="invalid_authentication_response",
            http_status=response.status_code,
        )
    return session


class PostgrestAcceptanceClient:
    """Narrow HTTP client exposing only GET and no-op PATCH operations."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        settings: Settings,
    ) -> None:
        self._client = client
        self._base_url = f"{str(settings.supabase_url).rstrip('/')}/rest/v1"
        self._publishable_key = settings.supabase_publishable_key
        self._timeout = settings.supabase_auth_timeout_seconds

    def _headers(
        self,
        session: PasswordSession | None,
        *,
        patch: bool = False,
    ) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "apikey": self._publishable_key.get_secret_value(),
        }
        if session is not None:
            headers["Authorization"] = (
                f"Bearer {session.access_token.get_secret_value()}"
            )
        if patch:
            headers["Prefer"] = "return=representation,count=exact"
            headers["Content-Type"] = "application/json"
        return headers

    async def get_relation(
        self,
        relation: str,
        *,
        params: Mapping[str, str],
        session: PasswordSession | None,
        check: str,
        actor: Actor,
    ) -> httpx.Response:
        return await self._request(
            method="GET",
            path=relation,
            params=params,
            session=session,
            check=check,
            actor=actor,
        )

    async def get_rpc(
        self,
        function_name: str,
        *,
        session: PasswordSession | None,
        check: str,
        actor: Actor,
    ) -> httpx.Response:
        return await self._request(
            method="GET",
            path=f"rpc/{function_name}",
            params={},
            session=session,
            check=check,
            actor=actor,
        )

    async def patch_relation(
        self,
        relation: str,
        *,
        params: Mapping[str, str],
        session: PasswordSession,
        body: Mapping[str, object],
        check: str,
        actor: Actor,
    ) -> httpx.Response:
        return await self._request(
            method="PATCH",
            path=relation,
            params=params,
            session=session,
            body=body,
            check=check,
            actor=actor,
        )

    async def _request(
        self,
        *,
        method: Literal["GET", "PATCH"],
        path: str,
        params: Mapping[str, str],
        session: PasswordSession | None,
        check: str,
        actor: Actor,
        body: Mapping[str, object] | None = None,
    ) -> httpx.Response:
        try:
            if method == "GET":
                return await self._client.get(
                    f"{self._base_url}/{path}",
                    params=params,
                    headers=self._headers(session),
                    timeout=self._timeout,
                )
            if session is None or body is None:
                raise AcceptanceFailure(
                    check=check,
                    actor=actor,
                    classification="unsafe_request_blocked",
                )
            return await self._client.patch(
                f"{self._base_url}/{path}",
                params=params,
                headers=self._headers(session, patch=True),
                json=body,
                timeout=self._timeout,
            )
        except AcceptanceFailure:
            raise
        except (httpx.TimeoutException, httpx.RequestError):
            raise AcceptanceFailure(
                check=check,
                actor=actor,
                classification="upstream_unavailable",
            ) from None


def _json_payload(response: httpx.Response, *, check: str, actor: Actor) -> object:
    try:
        return response.json()
    except ValueError:
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification="malformed_response",
            http_status=response.status_code,
        ) from None


def _row_list(
    response: httpx.Response,
    *,
    check: str,
    actor: Actor,
) -> list[dict[str, object]]:
    if response.status_code != httpx.codes.OK:
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification=_request_classification(response.status_code),
            http_status=response.status_code,
        )
    payload = _json_payload(response, check=check, actor=actor)
    if not isinstance(payload, list) or not all(
        isinstance(row, dict) for row in payload
    ):
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification="malformed_response",
            http_status=response.status_code,
        )
    return payload


def _secret_identifier(value: object, *, check: str, actor: Actor) -> SecretStr:
    if not isinstance(value, str):
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification="malformed_response",
        )
    try:
        normalized_identifier = str(UUID(value))
    except ValueError:
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification="malformed_response",
        ) from None
    return SecretStr(normalized_identifier)


def _snapshot(
    row: Mapping[str, object],
    *,
    relation: str,
    fields: tuple[str, ...],
    check: str,
    actor: Actor,
) -> RecordSnapshot:
    if set(row) != set(fields):
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification="malformed_response",
        )
    try:
        values = json.loads(json.dumps(dict(row)))
    except (TypeError, ValueError):
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification="malformed_response",
        ) from None
    return RecordSnapshot(
        relation=relation,
        fields=fields,
        identifier=_secret_identifier(values["id"], check=check, actor=actor),
        values=values,
    )


async def _read_rows(
    api: PostgrestAcceptanceClient,
    *,
    relation: str,
    fields: tuple[str, ...] | None,
    params: Mapping[str, str],
    session: PasswordSession | None,
    check: str,
    actor: Actor,
) -> list[dict[str, object]]:
    query = dict(params)
    query["select"] = "*" if fields is None else ",".join(fields)
    response = await api.get_relation(
        relation,
        params=query,
        session=session,
        check=check,
        actor=actor,
    )
    return _row_list(response, check=check, actor=actor)


async def _read_snapshot(
    api: PostgrestAcceptanceClient,
    *,
    expected: RecordSnapshot,
    session: PasswordSession,
    check: str,
    actor: Actor,
) -> RecordSnapshot:
    rows = await _read_rows(
        api,
        relation=expected.relation,
        fields=expected.fields,
        params={
            "id": f"eq.{expected.identifier.get_secret_value()}",
            "limit": "2",
        },
        session=session,
        check=check,
        actor=actor,
    )
    if len(rows) != 1:
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification="fixture_changed",
        )
    return _snapshot(
        rows[0],
        relation=expected.relation,
        fields=expected.fields,
        check=check,
        actor=actor,
    )


async def verify_public_catalogue_reads(
    api: PostgrestAcceptanceClient,
    *,
    session: PasswordSession | None,
    actor: Literal["anonymous", "customer"],
) -> None:
    for relation, fields in PUBLIC_CATALOGUE_READS.items():
        rows = await _read_rows(
            api,
            relation=relation,
            fields=fields,
            params={"limit": "1"},
            session=session,
            check="public_catalogue_read",
            actor=actor,
        )
        if len(rows) > 1:
            raise AcceptanceFailure(
                check="public_catalogue_read",
                actor=actor,
                classification="malformed_response",
            )
    response = await api.get_relation(
        "product",
        params=ELIGIBLE_CATALOGUE_PARAMS,
        session=session,
        check="eligible_catalogue_read",
        actor=actor,
    )
    if not _row_list(response, check="eligible_catalogue_read", actor=actor):
        raise AcceptanceFailure(
            check="eligible_catalogue_read",
            actor=actor,
            classification="fixture_precondition_not_met",
        )
    report_result(check="public_catalogue_read", actor=actor, status="passed")


async def verify_anonymous_denials(api: PostgrestAcceptanceClient) -> None:
    for relation in PRIVATE_ANONYMOUS_RELATIONS:
        response = await api.get_relation(
            relation,
            params={"select": "*", "limit": "1"},
            session=None,
            check="private_resource_denial",
            actor="anonymous",
        )
        if response.status_code == httpx.codes.OK:
            if _row_list(
                response,
                check="private_resource_denial",
                actor="anonymous",
            ):
                raise AcceptanceFailure(
                    check="private_resource_denial",
                    actor="anonymous",
                    classification="private_rows_exposed",
                    http_status=response.status_code,
                )
        elif response.status_code not in SAFE_PERMISSION_STATUSES:
            raise AcceptanceFailure(
                check="private_resource_denial",
                actor="anonymous",
                classification=_request_classification(response.status_code),
                http_status=response.status_code,
            )
    for function_name in RESTRICTED_HELPERS:
        response = await api.get_rpc(
            function_name,
            session=None,
            check="restricted_helper_denial",
            actor="anonymous",
        )
        if response.status_code not in SAFE_PERMISSION_STATUSES:
            raise AcceptanceFailure(
                check="restricted_helper_denial",
                actor="anonymous",
                classification="restricted_helper_executable",
                http_status=response.status_code,
            )
    report_result(check="anonymous_private_denials", actor="anonymous", status="passed")


async def _rpc_value(
    api: PostgrestAcceptanceClient,
    *,
    function_name: str,
    session: PasswordSession,
    actor: Literal["customer", "seller"],
    check: str,
) -> object:
    response = await api.get_rpc(
        function_name,
        session=session,
        check=check,
        actor=actor,
    )
    if response.status_code != httpx.codes.OK:
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification=_request_classification(response.status_code),
            http_status=response.status_code,
        )
    return _json_payload(response, check=check, actor=actor)


async def verify_customer_helpers(
    api: PostgrestAcceptanceClient,
    *,
    session: PasswordSession,
) -> None:
    expectations = (
        ("is_admin", False),
        ("current_marketplace_party_id", None),
        ("current_party_is_approved", False),
    )
    for function_name, expected in expectations:
        actual = await _rpc_value(
            api,
            function_name=function_name,
            session=session,
            actor="customer",
            check="customer_helper_result",
        )
        if actual is not expected:
            raise AcceptanceFailure(
                check="customer_helper_result",
                actor="customer",
                classification="unexpected_helper_result",
            )
    report_result(check="customer_helper_result", actor="customer", status="passed")


async def verify_seller_helpers(
    api: PostgrestAcceptanceClient,
    *,
    session: PasswordSession,
) -> SecretStr:
    is_admin = await _rpc_value(
        api,
        function_name="is_admin",
        session=session,
        actor="seller",
        check="seller_helper_result",
    )
    is_approved = await _rpc_value(
        api,
        function_name="current_party_is_approved",
        session=session,
        actor="seller",
        check="seller_helper_result",
    )
    party_id = await _rpc_value(
        api,
        function_name="current_marketplace_party_id",
        session=session,
        actor="seller",
        check="seller_helper_result",
    )
    if is_admin is not False or is_approved is not True:
        raise AcceptanceFailure(
            check="seller_helper_result",
            actor="seller",
            classification="unexpected_helper_result",
        )
    result = _secret_identifier(
        party_id,
        check="seller_helper_result",
        actor="seller",
    )
    report_result(check="seller_helper_result", actor="seller", status="passed")
    return result


async def _discover_party(
    api: PostgrestAcceptanceClient,
    *,
    seller_session: PasswordSession,
    customer_session: PasswordSession,
    party_id: SecretStr,
) -> RecordSnapshot:
    rows = await _read_rows(
        api,
        relation="marketplace_party",
        fields=PARTY_FIELDS,
        params={"id": f"eq.{party_id.get_secret_value()}", "limit": "2"},
        session=seller_session,
        check="fixture_discovery",
        actor="seller",
    )
    if len(rows) != 1:
        raise AcceptanceFailure(
            check="fixture_discovery",
            actor="seller",
            classification="fixture_precondition_not_met",
        )
    snapshot = _snapshot(
        rows[0],
        relation="marketplace_party",
        fields=PARTY_FIELDS,
        check="fixture_discovery",
        actor="seller",
    )
    if snapshot.identifier.get_secret_value() != party_id.get_secret_value():
        raise AcceptanceFailure(
            check="fixture_discovery",
            actor="seller",
            classification="ownership_mismatch",
        )
    if not await _snapshot_is_visible(
        api,
        expected=snapshot,
        session=customer_session,
        actor="customer",
    ):
        raise AcceptanceFailure(
            check="fixture_discovery",
            actor="customer",
            classification="fixture_precondition_not_met",
        )
    return snapshot


async def _snapshot_is_visible(
    api: PostgrestAcceptanceClient,
    *,
    expected: RecordSnapshot,
    session: PasswordSession,
    actor: Literal["customer", "seller"],
) -> bool:
    """Prove a PATCH actor can read an exact target without exposing its values."""

    rows = await _read_rows(
        api,
        relation=expected.relation,
        fields=expected.fields,
        params={
            "id": f"eq.{expected.identifier.get_secret_value()}",
            "limit": "2",
        },
        session=session,
        check="fixture_discovery",
        actor=actor,
    )
    if not rows:
        return False
    if len(rows) != 1:
        raise AcceptanceFailure(
            check="fixture_discovery",
            actor=actor,
            classification="malformed_response",
        )
    visible = _snapshot(
        rows[0],
        relation=expected.relation,
        fields=expected.fields,
        check="fixture_discovery",
        actor=actor,
    )
    if visible.values != expected.values:
        raise AcceptanceFailure(
            check="fixture_discovery",
            actor=actor,
            classification="fixture_changed",
        )
    return True


async def _discover_product_and_child(
    api: PostgrestAcceptanceClient,
    *,
    seller_session: PasswordSession,
    customer_session: PasswordSession,
    party_id: SecretStr,
    own: bool,
) -> tuple[RecordSnapshot, RecordSnapshot]:
    party_value = party_id.get_secret_value()
    rows = await _read_rows(
        api,
        relation="product",
        fields=PRODUCT_FIELDS,
        params={
            "marketplace_party_id": f"{'eq' if own else 'neq'}.{party_value}",
            "lifecycle_state": "eq.published",
            "order": "id.asc",
            "limit": "20",
        },
        session=seller_session,
        check="fixture_discovery",
        actor="seller",
    )
    for row in rows:
        product = _snapshot(
            row,
            relation="product",
            fields=PRODUCT_FIELDS,
            check="fixture_discovery",
            actor="seller",
        )
        owner = row.get("marketplace_party_id")
        if not isinstance(owner, str) or (owner == party_value) is not own:
            raise AcceptanceFailure(
                check="fixture_discovery",
                actor="seller",
                classification="ownership_mismatch",
            )
        child_rows = await _read_rows(
            api,
            relation="product_color",
            fields=PRODUCT_COLOR_FIELDS,
            params={
                "product_id": f"eq.{product.identifier.get_secret_value()}",
                "stock_quantity": "gt.0",
                "order": "id.asc",
                "limit": "1",
            },
            session=seller_session,
            check="fixture_discovery",
            actor="seller",
        )
        if not child_rows:
            continue
        child = _snapshot(
            child_rows[0],
            relation="product_color",
            fields=PRODUCT_COLOR_FIELDS,
            check="fixture_discovery",
            actor="seller",
        )
        if child.values.get("product_id") != product.identifier.get_secret_value():
            raise AcceptanceFailure(
                check="fixture_discovery",
                actor="seller",
                classification="ownership_mismatch",
            )
        if not await _snapshot_is_visible(
            api,
            expected=product,
            session=customer_session,
            actor="customer",
        ):
            continue
        if not await _snapshot_is_visible(
            api,
            expected=child,
            session=customer_session,
            actor="customer",
        ):
            continue
        return product, child
    raise AcceptanceFailure(
        check="fixture_discovery",
        actor="seller",
        classification="fixture_precondition_not_met",
    )


async def discover_acceptance_fixtures(
    api: PostgrestAcceptanceClient,
    *,
    seller_session: PasswordSession,
    customer_session: PasswordSession,
    seller_party_id: SecretStr,
) -> AcceptanceFixtures:
    """Complete every identity/value prerequisite before permitting a PATCH."""

    party = await _discover_party(
        api,
        seller_session=seller_session,
        customer_session=customer_session,
        party_id=seller_party_id,
    )
    own_product, own_child = await _discover_product_and_child(
        api,
        seller_session=seller_session,
        customer_session=customer_session,
        party_id=seller_party_id,
        own=True,
    )
    other_product, other_child = await _discover_product_and_child(
        api,
        seller_session=seller_session,
        customer_session=customer_session,
        party_id=seller_party_id,
        own=False,
    )
    if (
        own_product.identifier.get_secret_value()
        == other_product.identifier.get_secret_value()
        or own_child.identifier.get_secret_value()
        == other_child.identifier.get_secret_value()
    ):
        raise AcceptanceFailure(
            check="fixture_discovery",
            actor="seller",
            classification="ownership_mismatch",
        )
    fixtures = AcceptanceFixtures(
        seller_party=party,
        own_product=own_product,
        other_product=other_product,
        own_child=own_child,
        other_child=other_child,
    )
    report_result(check="fixture_discovery", actor="seller", status="passed")
    return fixtures


def _bounded_rows(
    rows: list[dict[str, object]],
    *,
    check: str,
    actor: Actor,
) -> list[dict[str, object]]:
    if not rows or len(rows) > MAX_FIXTURE_ROWS:
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification="fixture_precondition_not_met",
        )
    return rows


async def verify_financial_view_scope(
    api: PostgrestAcceptanceClient,
    *,
    session: PasswordSession,
    actor: Literal["customer", "seller"],
) -> None:
    """Require view order IDs to be a subset of directly visible order IDs."""

    permitted_orders = _bounded_rows(
        await _read_rows(
            api,
            relation="purchase_order",
            fields=("id",),
            params={"order": "id.asc", "limit": str(MAX_FIXTURE_ROWS + 1)},
            session=session,
            check="financial_view_scope",
            actor=actor,
        ),
        check="financial_view_scope",
        actor=actor,
    )
    view_rows = _bounded_rows(
        await _read_rows(
            api,
            relation="order_financial_position",
            fields=None,
            params={"limit": str(MAX_FIXTURE_ROWS + 1)},
            session=session,
            check="financial_view_scope",
            actor=actor,
        ),
        check="financial_view_scope",
        actor=actor,
    )
    permitted_ids = {
        _secret_identifier(
            row.get("id"), check="financial_view_scope", actor=actor
        ).get_secret_value()
        for row in permitted_orders
    }
    order_key = next(
        (
            candidate
            for candidate in ("purchase_order_id", "order_id", "id")
            if all(candidate in row for row in view_rows)
        ),
        None,
    )
    if order_key is None:
        raise AcceptanceFailure(
            check="financial_view_scope",
            actor=actor,
            classification="fixture_precondition_not_met",
        )
    view_order_ids = {
        _secret_identifier(
            row.get(order_key),
            check="financial_view_scope",
            actor=actor,
        ).get_secret_value()
        for row in view_rows
    }
    if not view_order_ids <= permitted_ids:
        raise AcceptanceFailure(
            check="financial_view_scope",
            actor=actor,
            classification="financial_scope_violation",
        )
    report_result(check="financial_view_scope", actor=actor, status="passed")


def _affected_count(response: httpx.Response) -> int | None:
    content_range = response.headers.get("content-range")
    if content_range is None:
        return None
    total = content_range.rpartition("/")[2]
    return int(total) if total.isdecimal() else None


async def probe_noop_patch(
    api: PostgrestAcceptanceClient,
    *,
    session: PasswordSession,
    actor: Literal["customer", "seller"],
    expected: RecordSnapshot,
    column: str,
    allowed: bool,
    check: str,
) -> None:
    """Read/PATCH/read one exact value and always verify post-PATCH equality."""

    before = await _read_snapshot(
        api,
        expected=expected,
        session=session,
        check=check,
        actor=actor,
    )
    if before.values != expected.values:
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification="fixture_changed",
        )
    patch_failure: AcceptanceFailure | None = None
    try:
        response = await api.patch_relation(
            expected.relation,
            params={
                "id": f"eq.{before.identifier.get_secret_value()}",
                "select": ",".join(before.fields),
            },
            session=session,
            body={column: before.existing_value(column)},
            check=check,
            actor=actor,
        )
        if allowed:
            rows = _row_list(response, check=check, actor=actor)
            if len(rows) != 1 or _affected_count(response) != 1:
                raise AcceptanceFailure(
                    check=check,
                    actor=actor,
                    classification="allowed_noop_not_applied_once",
                    http_status=response.status_code,
                )
            representation = _snapshot(
                rows[0],
                relation=before.relation,
                fields=before.fields,
                check=check,
                actor=actor,
            )
            if representation.values != before.values:
                raise AcceptanceFailure(
                    check=check,
                    actor=actor,
                    classification="business_values_changed",
                )
        elif response.status_code in SAFE_PERMISSION_STATUSES:
            pass
        elif response.status_code == httpx.codes.OK:
            rows = _row_list(response, check=check, actor=actor)
            if rows or _affected_count(response) != 0:
                raise AcceptanceFailure(
                    check=check,
                    actor=actor,
                    classification="forbidden_write_succeeded",
                    http_status=response.status_code,
                )
        else:
            raise AcceptanceFailure(
                check=check,
                actor=actor,
                classification="unexpected_permission_response",
                http_status=response.status_code,
            )
    except AcceptanceFailure as failure:
        patch_failure = failure

    try:
        after = await _read_snapshot(
            api,
            expected=before,
            session=session,
            check=check,
            actor=actor,
        )
    except AcceptanceFailure:
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification="post_patch_verification_failed",
        ) from None
    if after.values != before.values:
        raise AcceptanceFailure(
            check=check,
            actor=actor,
            classification="business_values_changed",
        )
    if patch_failure is not None:
        raise patch_failure
    report_result(check=check, actor=actor, status="passed")


async def run_noop_patch_matrix(
    api: PostgrestAcceptanceClient,
    *,
    customer_session: PasswordSession,
    seller_session: PasswordSession,
    fixtures: AcceptanceFixtures,
) -> None:
    probes = (
        (
            customer_session,
            "customer",
            fixtures.seller_party,
            "business_description",
            False,
            "customer_marketplace_party_denial",
        ),
        (
            customer_session,
            "customer",
            fixtures.own_product,
            "description",
            False,
            "customer_product_denial",
        ),
        (
            seller_session,
            "seller",
            fixtures.seller_party,
            "business_description",
            True,
            "seller_party_profile_noop",
        ),
        (
            seller_session,
            "seller",
            fixtures.seller_party,
            "approval_state",
            False,
            "seller_approval_state_denial",
        ),
        (
            seller_session,
            "seller",
            fixtures.seller_party,
            "state_reason",
            False,
            "seller_state_reason_denial",
        ),
        (
            seller_session,
            "seller",
            fixtures.own_product,
            "description",
            True,
            "seller_own_product_noop",
        ),
        (
            seller_session,
            "seller",
            fixtures.other_product,
            "description",
            False,
            "seller_other_product_denial",
        ),
        (
            seller_session,
            "seller",
            fixtures.own_child,
            "color_value",
            True,
            "seller_own_child_noop",
        ),
        (
            seller_session,
            "seller",
            fixtures.other_child,
            "color_value",
            False,
            "seller_other_child_denial",
        ),
    )
    for session, actor, target, column, allowed, check in probes:
        await probe_noop_patch(
            api,
            session=session,
            actor=actor,
            expected=target,
            column=column,
            allowed=allowed,
            check=check,
        )


async def run_acceptance_checks(
    *,
    settings: Settings,
    customer_session: PasswordSession,
    seller_session: PasswordSession,
    client: httpx.AsyncClient,
) -> None:
    api = PostgrestAcceptanceClient(client=client, settings=settings)
    await verify_public_catalogue_reads(api, session=None, actor="anonymous")
    await verify_anonymous_denials(api)
    await verify_public_catalogue_reads(
        api,
        session=customer_session,
        actor="customer",
    )
    await verify_customer_helpers(api, session=customer_session)
    seller_party_id = await verify_seller_helpers(api, session=seller_session)
    fixtures = await discover_acceptance_fixtures(
        api,
        seller_session=seller_session,
        customer_session=customer_session,
        seller_party_id=seller_party_id,
    )
    await verify_financial_view_scope(
        api,
        session=customer_session,
        actor="customer",
    )
    await verify_financial_view_scope(
        api,
        session=seller_session,
        actor="seller",
    )
    await run_noop_patch_matrix(
        api,
        customer_session=customer_session,
        seller_session=seller_session,
        fixtures=fixtures,
    )


async def async_main() -> None:
    reject_forbidden_secret_configuration()
    secrets = collect_interactive_secrets()
    try:
        settings = load_settings()
    except RuntimeError:
        raise AcceptanceFailure(
            check="configuration",
            classification="invalid_configuration",
        ) from None

    logging.getLogger("httpx").disabled = True
    logging.getLogger("httpcore").disabled = True
    async with httpx.AsyncClient() as auth_client:
        customer_session = await sign_in(
            client=auth_client,
            settings=settings,
            actor="customer",
            email=CUSTOMER_EMAIL,
            password=secrets.customer_password,
        )
        report_result(
            check="password_authentication",
            actor="customer",
            status="passed",
        )
        seller_session = await sign_in(
            client=auth_client,
            settings=settings,
            actor="seller",
            email=SELLER_EMAIL,
            password=secrets.seller_password,
        )
        report_result(
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
    except AcceptanceFailure as failure:
        report_result(
            check=failure.check,
            actor=failure.actor,
            status="failed",
            classification=failure.classification,
            http_status=failure.http_status,
        )
        return 1
    except KeyboardInterrupt:
        report_result(
            check="credential_input",
            actor="runner",
            status="failed",
            classification="credential_input_cancelled",
        )
        return 1
    except Exception:
        report_result(
            check="live_rls_acceptance",
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
