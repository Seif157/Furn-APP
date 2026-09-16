"""Deterministic safety tests for the Phase 3.2D live acceptance utility."""

import inspect
import json
from io import StringIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from scripts import live_phase_3_2d_acceptance as acceptance
from scripts import live_rls_acceptance as base
from tests import phase_3_2d_package as package

TEST_PUBLISHABLE_KEY = "sb_publishable_phase32d_sentinel"
TEST_ACCESS_TOKEN = "<access-token-sentinel>"
TEST_REFRESH_TOKEN = "<refresh-token-sentinel>"
TEST_PASSWORD = "<password-sentinel>"


def _test_identifier(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"phase-3.2d:{label}"))


CUSTOMER_ID = _test_identifier("customer")
SELLER_ID = _test_identifier("seller")
IDS = {
    name: _test_identifier(name)
    for name in (
        "address",
        "cart",
        "cart_line",
        "color",
        "saved_space",
        "review",
        "product",
        "pending_request",
        "locked_request",
        "service_type",
        "customer_order",
        "seller_order",
        "offering",
        "design",
        "submitted_offer",
        "locked_offer",
        "submitted_line",
        "locked_line",
        "design_version",
        "furnishing_request",
    )
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class TTYStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def build_settings() -> Settings:
    return Settings(
        SUPABASE_URL="://".join(("https", "testing.invalid")),
        SUPABASE_PUBLISHABLE_KEY=TEST_PUBLISHABLE_KEY,
        SUPABASE_AUTH_TIMEOUT_SECONDS=5.0,
        _env_file=None,
    )


def build_session(token: str = TEST_ACCESS_TOKEN) -> base.PasswordSession:
    return base.PasswordSession(
        access_token=SecretStr(token),
        refresh_token=SecretStr(TEST_REFRESH_TOKEN),
    )


def _row(fields: tuple[str, ...], **values: object) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(fields)
    row.update(values)
    assert set(row) == set(fields)
    return row


def address_row() -> dict[str, object]:
    return _row(
        acceptance.ADDRESS_FIELDS,
        id=IDS["address"],
        customer_profile_id=CUSTOMER_ID,
        label="home",
        recipient_name="r",
        contact_phone="p",
        address_line_1="l",
        city="c",
        country="x",
        is_default=False,
    )


def cart_row() -> dict[str, object]:
    return _row(acceptance.CART_FIELDS, id=IDS["cart"], customer_profile_id=CUSTOMER_ID)


def cart_line_row() -> dict[str, object]:
    return _row(
        acceptance.CART_LINE_FIELDS,
        id=IDS["cart_line"],
        cart_id=IDS["cart"],
        product_color_id=IDS["color"],
        quantity=1,
    )


def saved_space_row() -> dict[str, object]:
    return _row(
        acceptance.SAVED_SPACE_FIELDS,
        id=IDS["saved_space"],
        customer_profile_id=CUSTOMER_ID,
        space_name="s",
        width_cm="1.00",
        depth_cm="1.00",
    )


def review_row() -> dict[str, object]:
    return _row(
        acceptance.REVIEW_FIELDS,
        id=IDS["review"],
        customer_profile_id=CUSTOMER_ID,
        target_kind="product",
        target_product_id=IDS["product"],
        rating=5,
        created_at="2026-01-01T00:00:00Z",
    )


def service_request_row(state: str) -> dict[str, object]:
    key = "pending_request" if state == "pending" else "locked_request"
    return _row(
        acceptance.SERVICE_REQUEST_FIELDS,
        id=IDS[key],
        customer_profile_id=CUSTOMER_ID,
        service_type_id=IDS["service_type"],
        marketplace_party_id=None if state == "pending" else SELLER_ID,
        address_id=IDS["address"],
        lifecycle_state=state,
        created_at="2026-01-01T00:00:00Z",
    )


OTHER_CUSTOMER_ID = _test_identifier("other-customer")
OTHER_SELLER_ID = _test_identifier("other-seller")


def order_row(owner: str) -> dict[str, object]:
    # The customer's order belongs to another seller and the seller's order to
    # another customer, so each actor discovers exactly one distinct order.
    return _row(
        acceptance.PURCHASE_ORDER_FIELDS,
        id=IDS[f"{owner}_order"],
        customer_profile_id=CUSTOMER_ID if owner == "customer" else OTHER_CUSTOMER_ID,
        marketplace_party_id=SELLER_ID if owner == "seller" else OTHER_SELLER_ID,
        address_id=IDS["address"],
        origin="stocked",
        lifecycle_state="pending",
        delivery_fee="0",
        placed_at="2026-01-01T00:00:00Z",
    )


def offering_row() -> dict[str, object]:
    return _row(
        acceptance.CUSTOM_OFFERING_FIELDS,
        id=IDS["offering"],
        marketplace_party_id=SELLER_ID,
        design_id=IDS["design"],
        published_price="10.00",
        title="t",
        publication_state="unpublished",
    )


def line_row(kind: str) -> dict[str, object]:
    return _row(
        acceptance.OFFER_LINE_ITEM_FIELDS,
        id=IDS[f"{kind}_line"],
        offer_id=IDS[f"{kind}_offer"],
        line_kind="custom",
        item_name="i",
        unit_price="1.00",
        quantity=1,
        line_total="1.00",
        display_order=0,
    )


def capability_row() -> dict[str, object]:
    return _row(
        acceptance.PARTY_CAPABILITY_FIELDS,
        marketplace_party_id=SELLER_ID,
        service_type_id=IDS["service_type"],
    )


def design_reference_row() -> dict[str, object]:
    return {"design_id": IDS["design"], "product_id": IDS["product"]}


def request_design_version_row() -> dict[str, object]:
    return {
        "furnishing_request_id": IDS["furnishing_request"],
        "design_version_id": IDS["design_version"],
    }


def snapshot(relation: str, fields: tuple[str, ...], row: dict[str, object]):
    return base.RecordSnapshot(
        relation=relation,
        fields=fields,
        identifier=SecretStr(str(row["id"])),
        values=row,
    )


def link(relation: str, fields: tuple[str, ...], row: dict[str, object]):
    return acceptance.LinkRow(
        relation=relation,
        fields=fields,
        key={
            column: SecretStr(str(row[column]))
            for column in fields
            if column.endswith("_id")
        },
        values=row,
    )


def customer_fixtures() -> acceptance.CustomerFixtures:
    return acceptance.CustomerFixtures(
        address=snapshot("address", acceptance.ADDRESS_FIELDS, address_row()),
        cart=snapshot("cart", acceptance.CART_FIELDS, cart_row()),
        cart_line=snapshot("cart_line", acceptance.CART_LINE_FIELDS, cart_line_row()),
        saved_space=snapshot(
            "saved_space", acceptance.SAVED_SPACE_FIELDS, saved_space_row()
        ),
        review=snapshot("review", acceptance.REVIEW_FIELDS, review_row()),
        pending_request=snapshot(
            "service_request",
            acceptance.SERVICE_REQUEST_FIELDS,
            service_request_row("pending"),
        ),
        locked_request=snapshot(
            "service_request",
            acceptance.SERVICE_REQUEST_FIELDS,
            service_request_row("completed"),
        ),
        order=snapshot(
            "purchase_order", acceptance.PURCHASE_ORDER_FIELDS, order_row("customer")
        ),
        design_reference=link(
            "design_product_reference",
            acceptance.DESIGN_PRODUCT_REFERENCE_FIELDS,
            design_reference_row(),
        ),
        request_design_version=link(
            "furnishing_request_design_version",
            acceptance.FURNISHING_REQUEST_DESIGN_VERSION_FIELDS,
            request_design_version_row(),
        ),
    )


def seller_fixtures() -> acceptance.SellerFixtures:
    return acceptance.SellerFixtures(
        offering=snapshot(
            "custom_offering", acceptance.CUSTOM_OFFERING_FIELDS, offering_row()
        ),
        submitted_line=snapshot(
            "offer_line_item", acceptance.OFFER_LINE_ITEM_FIELDS, line_row("submitted")
        ),
        locked_line=snapshot(
            "offer_line_item", acceptance.OFFER_LINE_ITEM_FIELDS, line_row("locked")
        ),
        order=snapshot(
            "purchase_order", acceptance.PURCHASE_ORDER_FIELDS, order_row("seller")
        ),
        capability=link(
            "party_capability", acceptance.PARTY_CAPABILITY_FIELDS, capability_row()
        ),
    )


ALL_ROWS: dict[str, list[dict[str, object]]] = {
    "address": [address_row()],
    "cart": [cart_row()],
    "cart_line": [cart_line_row()],
    "saved_space": [saved_space_row()],
    "review": [review_row()],
    "service_request": [
        service_request_row("pending"),
        service_request_row("completed"),
    ],
    "purchase_order": [order_row("customer"), order_row("seller")],
    "custom_offering": [offering_row()],
    "offer_line_item": [line_row("submitted"), line_row("locked")],
    "party_capability": [capability_row()],
    "design_product_reference": [design_reference_row()],
    "furnishing_request_design_version": [request_design_version_row()],
    "design": [{"id": IDS["design"]}],
    "furnishing_request": [
        {"id": IDS["furnishing_request"], "customer_profile_id": CUSTOMER_ID}
    ],
    "offer": [
        {
            "id": IDS["submitted_offer"],
            "marketplace_party_id": SELLER_ID,
            "lifecycle_state": "submitted",
        },
        {
            "id": IDS["locked_offer"],
            "marketplace_party_id": SELLER_ID,
            "lifecycle_state": "accepted",
        },
    ],
}
ALLOWED_PATCHES = {
    ("address", "label"),
    ("cart_line", "quantity"),
    ("saved_space", "space_name"),
    ("service_request", "details"),
    ("custom_offering", "title"),
    ("offer_line_item", "quantity"),
    ("purchase_order", "notes"),
}


def _matches(row: dict[str, object], params: httpx.QueryParams) -> bool:
    for key, value in params.items():
        if key in {"select", "limit", "order"}:
            continue
        actual = row.get(key)
        if value.startswith("eq."):
            if str(actual) != value[3:]:
                return False
        elif value.startswith("neq."):
            if str(actual) == value[4:]:
                return False
        elif value.startswith("in.("):
            if str(actual) not in value[4:-1].split(","):
                return False
        else:
            raise AssertionError(f"unsupported filter {value}")
    return True


def _project(row: dict[str, object], select: str | None) -> dict[str, object]:
    if select is None or select == "*":
        return dict(row)
    return {column: row.get(column) for column in select.split(",")}


def fixture_handler(request: httpx.Request) -> httpx.Response:
    """A deterministic PostgREST stand-in for the full acceptance flow."""

    path = request.url.path
    if "/rpc/" in path:
        function = path.rsplit("/", 1)[-1]
        if "authorization" not in request.headers:
            return httpx.Response(403, json={"message": "private"})
        if function == "current_customer_profile_id":
            return httpx.Response(200, json=CUSTOMER_ID)
        if function == "current_marketplace_party_id":
            return httpx.Response(200, json=SELLER_ID)
        if function == "is_admin":
            return httpx.Response(200, json=False)
        if function == "current_party_is_approved":
            return httpx.Response(200, json=True)
        raise AssertionError(f"unexpected rpc {function}")
    relation = path.rsplit("/", 1)[-1]
    params = request.url.params
    select = params.get("select")
    anonymous = "authorization" not in request.headers
    if relation == "marketplace_party":
        columns = set((select or "*").split(","))
        hidden = {"user_id"} if not anonymous else {"user_id", "state_reason"}
        if columns & hidden:
            return httpx.Response(403, json={"message": "private"})
        row = {
            "id": SELLER_ID,
            "business_name": "b",
            "business_description": None,
            "logo_url": None,
            "coverage_area": None,
            "approval_state": "approved",
            "state_reason": None,
        }
        return httpx.Response(200, json=[_project(row, select)])
    if relation == "order_financial_position":
        return httpx.Response(200, json=[{"purchase_order_id": IDS["customer_order"]}])
    rows = [row for row in ALL_ROWS[relation] if _matches(row, params)]
    if request.method == "PATCH":
        body = json.loads(request.content)
        (column,) = body
        if (relation, column) in ALLOWED_PATCHES and len(rows) == 1:
            row = rows[0]
            locked = (
                relation == "service_request" and row["lifecycle_state"] != "pending"
            )
            locked |= relation == "offer_line_item" and row["id"] == IDS["locked_line"]
            locked |= (
                relation == "purchase_order" and row["id"] == IDS["customer_order"]
            )
            if not locked:
                return httpx.Response(
                    200,
                    json=[_project(row, select)],
                    headers={"Content-Range": "0-0/1"},
                )
            return httpx.Response(200, json=[], headers={"Content-Range": "*/0"})
        return httpx.Response(403, json={"message": "private"})
    return httpx.Response(200, json=[_project(row, select) for row in rows])


def test_reuses_exact_interactive_branch_and_credential_safety(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(base.sys, "stdin", TTYStringIO())
    monkeypatch.setattr(base.sys, "stderr", TTYStringIO())
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: base.TEST_BRANCH_CONFIRMATION,
    )
    passwords = iter((TEST_PASSWORD, f"seller-{TEST_PASSWORD}"))
    monkeypatch.setattr(base.getpass, "getpass", lambda _prompt: next(passwords))
    secrets = base.collect_interactive_secrets()
    assert secrets.model_dump() == {}
    assert TEST_PASSWORD not in repr(secrets)
    assert TEST_PASSWORD not in capsys.readouterr().out


@pytest.mark.parametrize("name", sorted(base.FORBIDDEN_SECRET_ENVIRONMENT_NAMES))
def test_refuses_every_service_secret_configuration(name: str) -> None:
    with pytest.raises(base.AcceptanceFailure) as error:
        base.reject_forbidden_secret_configuration({name: "not-read"})
    assert error.value.classification == "forbidden_secret_configuration"


@pytest.mark.anyio
async def test_full_flow_issues_only_get_and_noop_patch_in_the_documented_order() -> (
    None
):
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.method == "PATCH" else None
        calls.append((request.method, request.url.path.rsplit("/", 1)[-1], body))
        return fixture_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await acceptance.run_acceptance_checks(
            settings=build_settings(),
            customer_session=build_session(),
            seller_session=build_session("seller-token"),
            client=client,
        )
    assert {method for method, _relation, _body in calls} == {"GET", "PATCH"}
    patches = [
        (relation, body) for method, relation, body in calls if method == "PATCH"
    ]
    assert patches == [
        ("address", {"label": "home"}),
        ("address", {"customer_profile_id": CUSTOMER_ID}),
        ("cart", {"customer_profile_id": CUSTOMER_ID}),
        ("cart_line", {"quantity": 1}),
        ("cart_line", {"cart_id": IDS["cart"]}),
        ("saved_space", {"space_name": "s"}),
        ("saved_space", {"customer_profile_id": CUSTOMER_ID}),
        ("review", {"rating": 5}),
        ("review", {"comment": None}),
        ("service_request", {"details": None}),
        ("service_request", {"lifecycle_state": "pending"}),
        ("service_request", {"marketplace_party_id": None}),
        ("service_request", {"details": None}),
        ("purchase_order", {"notes": None}),
        ("design_product_reference", {"product_id": IDS["product"]}),
        (
            "furnishing_request_design_version",
            {"design_version_id": IDS["design_version"]},
        ),
        ("custom_offering", {"title": "t"}),
        ("custom_offering", {"marketplace_party_id": SELLER_ID}),
        ("offer_line_item", {"quantity": 1}),
        ("offer_line_item", {"offer_id": IDS["submitted_offer"]}),
        ("offer_line_item", {"quantity": 1}),
        ("purchase_order", {"notes": None}),
        ("purchase_order", {"lifecycle_state": "pending"}),
        ("party_capability", {"declared_at": None}),
    ]
    # Every PATCH is preceded and followed by a GET of the same relation.
    for index, (method, relation, _body) in enumerate(calls):
        if method == "PATCH":
            assert calls[index - 1][:2] == ("GET", relation)
            assert calls[index + 1][:2] == ("GET", relation)


@pytest.mark.anyio
async def test_party_column_boundary_fails_closed_on_exposure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        select = request.url.params.get("select", "")
        if select == "user_id":
            return httpx.Response(200, json=[{"user_id": CUSTOMER_ID}])
        return fixture_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        with pytest.raises(base.AcceptanceFailure) as error:
            await acceptance.verify_party_column_boundary(
                api, customer_session=build_session()
            )
    assert error.value.classification == "private_column_exposed"
    assert error.value.actor == "anonymous"


@pytest.mark.anyio
async def test_party_public_read_rejects_unapproved_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        select = request.url.params.get("select", "")
        if select in {"user_id", "state_reason"}:
            return httpx.Response(403)
        if "authorization" not in request.headers:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": SELLER_ID,
                        "business_name": "b",
                        "business_description": None,
                        "logo_url": None,
                        "coverage_area": None,
                        "approval_state": "pending",
                    }
                ],
            )
        return fixture_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        with pytest.raises(base.AcceptanceFailure) as error:
            await acceptance.verify_party_column_boundary(
                api, customer_session=build_session()
            )
    assert error.value.classification == "unapproved_party_exposed"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "missing",
    ["service_request", "design_product_reference", "offer_line_item"],
)
async def test_missing_fixture_fails_before_any_patch(missing: str) -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        relation = request.url.path.rsplit("/", 1)[-1]
        if relation == missing:
            return httpx.Response(200, json=[])
        return fixture_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        with pytest.raises(base.AcceptanceFailure) as error:
            if missing == "offer_line_item":
                await acceptance.discover_seller_fixtures(
                    api,
                    seller_session=build_session(),
                    seller_party_id=SecretStr(SELLER_ID),
                )
            else:
                await acceptance.discover_customer_fixtures(
                    api,
                    customer_session=build_session(),
                    customer_profile_id=SecretStr(CUSTOMER_ID),
                )
    assert error.value.classification == "fixture_precondition_not_met"
    assert set(methods) == {"GET"}


@pytest.mark.anyio
async def test_pending_request_with_assigned_party_is_not_a_valid_fixture() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        relation = request.url.path.rsplit("/", 1)[-1]
        if (
            relation == "service_request"
            and request.url.params.get("lifecycle_state") == "eq.pending"
        ):
            row = service_request_row("pending")
            row["marketplace_party_id"] = SELLER_ID
            return httpx.Response(200, json=[row])
        return fixture_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        with pytest.raises(base.AcceptanceFailure) as error:
            await acceptance.discover_customer_fixtures(
                api,
                customer_session=build_session(),
                customer_profile_id=SecretStr(CUSTOMER_ID),
            )
    assert error.value.classification == "fixture_precondition_not_met"


@pytest.mark.anyio
async def test_forbidden_write_that_succeeds_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            body = json.loads(request.content)
            if "lifecycle_state" in body:
                row = service_request_row("pending")
                return httpx.Response(
                    200, json=[row], headers={"Content-Range": "0-0/1"}
                )
        return fixture_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        with pytest.raises(base.AcceptanceFailure) as error:
            await acceptance.verify_customer_write_boundaries(
                api,
                customer_session=build_session(),
                fixtures=customer_fixtures(),
            )
    assert error.value.classification == "forbidden_write_succeeded"
    assert error.value.check == "customer_request_direct_lifecycle_denial"


@pytest.mark.anyio
async def test_link_probe_detects_changed_values_and_successful_writes() -> None:
    mutated = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        relation = request.url.path.rsplit("/", 1)[-1]
        if relation == "party_capability":
            if request.method == "PATCH":
                return httpx.Response(
                    200,
                    json=[capability_row()],
                    headers={"Content-Range": "0-0/1"},
                )
            mutated["calls"] += 1
        return fixture_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = base.PostgrestAcceptanceClient(client=client, settings=build_settings())
        with pytest.raises(base.AcceptanceFailure) as error:
            await acceptance.probe_link_noop_patch_denied(
                api,
                session=build_session(),
                actor="seller",
                expected=seller_fixtures().capability,
                column="declared_at",
                check="seller_capability_update_denial",
            )
    assert error.value.classification == "forbidden_write_succeeded"
    assert mutated["calls"] == 2  # read before and read after the PATCH


def test_unexpected_failure_output_redacts_rows_tokens_and_uuids(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = f"{TEST_ACCESS_TOKEN} {CUSTOMER_ID} private-notes"

    async def fail() -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(acceptance, "async_main", fail)
    assert acceptance.main() == 1
    output = capsys.readouterr().out
    assert output == (
        "check=live_phase_3_2d_acceptance actor=runner status=failed "
        "safe_error_classification=unexpected_internal_error\n"
    )
    assert secret not in output


def test_utility_has_no_data_post_delete_transition_or_service_role_path() -> None:
    source = Path(inspect.getsourcefile(acceptance) or "").read_text(encoding="utf-8")
    lower_source = source.lower()
    assert ".post(" not in lower_source
    assert ".delete(" not in lower_source
    assert "service_role" not in lower_source
    assert "supabase_secret" not in lower_source
    assert "sql editor" not in lower_source
    assert "base.probe_noop_patch" in source
    for function_name in (
        "cancel_service_request",
        "accept_service_request",
        "start_service_request",
        "complete_service_request",
        "advance_purchase_order",
        "cancel_purchase_order",
        "open_furnishing_request",
        "withdraw_furnishing_request",
    ):
        assert function_name not in source


def test_field_tuples_match_the_evidence_inventory_exactly() -> None:
    columns = package.columns()
    expected = {
        "address": acceptance.ADDRESS_FIELDS,
        "cart": acceptance.CART_FIELDS,
        "cart_line": acceptance.CART_LINE_FIELDS,
        "saved_space": acceptance.SAVED_SPACE_FIELDS,
        "review": acceptance.REVIEW_FIELDS,
        "service_request": acceptance.SERVICE_REQUEST_FIELDS,
        "purchase_order": acceptance.PURCHASE_ORDER_FIELDS,
        "custom_offering": acceptance.CUSTOM_OFFERING_FIELDS,
        "offer_line_item": acceptance.OFFER_LINE_ITEM_FIELDS,
        "party_capability": acceptance.PARTY_CAPABILITY_FIELDS,
        "design_product_reference": acceptance.DESIGN_PRODUCT_REFERENCE_FIELDS,
        "furnishing_request_design_version": (
            acceptance.FURNISHING_REQUEST_DESIGN_VERSION_FIELDS
        ),
    }
    for table, fields in expected.items():
        assert fields == tuple(column.name for column in columns[table]), table
    assert acceptance.PARTY_PUBLIC_FIELDS == package.PARTY_ANON_SELECT
    assert acceptance.PARTY_AUTHENTICATED_FIELDS == package.PARTY_AUTHENTICATED_SELECT
    assert acceptance.PARTY_HIDDEN_COLUMN not in acceptance.PARTY_AUTHENTICATED_FIELDS


def test_probe_matrix_matches_the_allowlists_and_immutable_columns() -> None:
    relation_of = {
        "address": "address",
        "cart": "cart",
        "cart_line": "cart_line",
        "saved_space": "saved_space",
        "review": "review",
        "pending_request": "service_request",
        "locked_request": "service_request",
        "order": "purchase_order",
        "offering": "custom_offering",
        "submitted_line": "offer_line_item",
        "locked_line": "offer_line_item",
    }
    for attribute, column, allowed, check in acceptance.CUSTOMER_PROBES:
        table = relation_of[attribute]
        granted = column in package.UPDATE_ALLOWLIST.get(table, ())
        if allowed:
            assert granted, (attribute, column)
        elif attribute in {"locked_request", "order"}:
            assert granted, (attribute, column)  # denied by policy, not by grant
        else:
            assert not granted, (attribute, column)
        assert base.SAFE_LABEL.fullmatch(check)
    for attribute, column, allowed, check in acceptance.SELLER_PROBES:
        table = relation_of[attribute]
        granted = column in package.UPDATE_ALLOWLIST.get(table, ())
        if allowed or attribute == "locked_line":
            assert granted, (attribute, column)
        else:
            assert not granted, (attribute, column)
        assert base.SAFE_LABEL.fullmatch(check)
    assert acceptance.LOCKED_SERVICE_STATES == (
        "accepted",
        "in_progress",
        "completed",
        "cancelled",
    )
