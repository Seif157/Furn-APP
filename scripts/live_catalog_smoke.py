"""Secure interactive smoke test for the live Supabase catalogue integration."""

import asyncio
import getpass
import logging
import sys
import warnings
from collections.abc import Mapping
from typing import Literal, NoReturn
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.auth.models import AuthenticatedRequestContext, MeResponse
from app.catalog.models import ProductListResponse, ProductResponse
from app.catalog.transform import is_recommendation_eligible
from app.config import Settings, load_settings
from app.main import app

DEFAULT_LIMIT = 20
DEFAULT_OFFSET = 0
FORBIDDEN_RESPONSE_FIELDS = frozenset(
    {
        "access_token",
        "approval_state",
        "authenticated",
        "confirmation_state",
        "internal_reason",
        "is_active",
        "lifecycle_state",
        "moderation_reason",
        "moderation_state",
        "provider_data",
        "refresh_token",
        "rejection_reason",
        "user_id",
        "user_metadata",
    }
)
SAFE_API_ERROR_CODES = frozenset(
    {
        "authentication_required",
        "authentication_service_unavailable",
        "catalogue_service_unavailable",
        "catalogue_upstream_error",
        "invalid_access_token",
        "product_not_found",
    }
)


class PasswordSession(BaseModel):
    """Secret-bearing session data that remains in memory and displays redacted."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    access_token: SecretStr = Field(exclude=True, repr=False)
    refresh_token: SecretStr = Field(exclude=True, repr=False)


class SmokeFailure(Exception):
    """Safe failure metadata with no upstream or credential content."""

    def __init__(
        self,
        *,
        check: str,
        classification: str,
        http_status: int | None = None,
    ) -> None:
        super().__init__(classification)
        self.check = check
        self.classification = classification
        self.http_status = http_status


def report_result(
    *,
    check: str,
    status: Literal["passed", "failed"],
    http_status: int | None = None,
    product_count: int | None = None,
    classification: str | None = None,
) -> None:
    """Print only fields explicitly permitted by the smoke-test contract."""

    fields = [f"check={check}", f"status={status}"]
    if http_status is not None:
        fields.append(f"http_status={http_status}")
    if product_count is not None:
        fields.append(f"product_count={product_count}")
    if classification is not None:
        fields.append(f"safe_error_classification={classification}")
    print(" ".join(fields), flush=True)


def collect_credentials() -> tuple[str, str]:
    """Collect credentials only when getpass can use an interactive terminal."""

    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise SmokeFailure(
            check="credential_input",
            classification="secure_terminal_required",
        )

    try:
        email = input().strip()
    except (EOFError, KeyboardInterrupt):
        raise SmokeFailure(
            check="credential_input",
            classification="credential_input_cancelled",
        ) from None

    if not email:
        raise SmokeFailure(
            check="credential_input",
            classification="credentials_required",
        )
    report_result(check="email_input", status="passed")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("")
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        raise SmokeFailure(
            check="credential_input",
            classification="secure_terminal_required",
        ) from None

    if not password:
        raise SmokeFailure(
            check="credential_input",
            classification="credentials_required",
        )
    report_result(check="password_input", status="passed")
    return email, password


async def sign_in(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    email: str,
    password: str,
) -> tuple[PasswordSession, int]:
    """Authenticate with Supabase while keeping all session data in memory."""

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
            json={"email": email, "password": password},
            timeout=settings.supabase_auth_timeout_seconds,
        )
    except (httpx.TimeoutException, httpx.RequestError):
        raise SmokeFailure(
            check="password_authentication",
            classification="authentication_service_unavailable",
        ) from None

    http_status = response.status_code
    if http_status != httpx.codes.OK:
        classification = (
            "authentication_rejected"
            if 400 <= http_status < 500 and http_status != 429
            else "authentication_service_unavailable"
        )
        raise SmokeFailure(
            check="password_authentication",
            classification=classification,
            http_status=http_status,
        )

    try:
        session = PasswordSession.model_validate_json(response.content, strict=True)
    except ValidationError:
        raise SmokeFailure(
            check="password_authentication",
            classification="invalid_authentication_response",
            http_status=http_status,
        ) from None

    if (
        not session.access_token.get_secret_value()
        or not session.refresh_token.get_secret_value()
    ):
        raise SmokeFailure(
            check="password_authentication",
            classification="invalid_authentication_response",
            http_status=http_status,
        )
    return session, http_status


def response_keys(value: object) -> set[str]:
    """Collect JSON object keys recursively without retaining or printing values."""

    if isinstance(value, Mapping):
        keys = {str(key) for key in value}
        for child in value.values():
            keys.update(response_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(response_keys(child))
        return keys
    return set()


def require_status(
    response: httpx.Response,
    *,
    check: str,
    expected_status: int,
) -> None:
    if response.status_code != expected_status:
        raise SmokeFailure(
            check=check,
            classification=safe_api_error_classification(response),
            http_status=response.status_code,
        )


def safe_api_error_classification(response: httpx.Response) -> str:
    """Return only a known public error code, never an upstream response body."""

    try:
        payload = response.json()
        code = payload["detail"]["code"]
    except (KeyError, TypeError, ValueError):
        return "unexpected_http_status"
    return code if code in SAFE_API_ERROR_CODES else "unexpected_http_status"


def validate_health(response: httpx.Response) -> None:
    require_status(response, check="health", expected_status=200)
    try:
        payload = response.json()
    except ValueError:
        raise SmokeFailure(
            check="health",
            classification="invalid_response_shape",
            http_status=response.status_code,
        ) from None
    if payload != {
        "status": "ok",
        "service": "furniture-ai-api",
        "version": "0.1.0",
    }:
        raise SmokeFailure(
            check="health",
            classification="invalid_response_shape",
            http_status=response.status_code,
        )


def validate_me(response: httpx.Response) -> MeResponse:
    require_status(response, check="current_user", expected_status=200)
    try:
        current_user = MeResponse.model_validate_json(response.content, strict=True)
    except ValidationError:
        raise SmokeFailure(
            check="current_user",
            classification="invalid_response_shape",
            http_status=response.status_code,
        ) from None
    if not current_user.authenticated:
        raise SmokeFailure(
            check="current_user",
            classification="invalid_authenticated_user",
            http_status=response.status_code,
        )
    return current_user


def validate_catalogue(response: httpx.Response) -> ProductListResponse:
    require_status(response, check="catalogue_list", expected_status=200)
    try:
        raw_payload = response.json()
        catalogue = ProductListResponse.model_validate_json(
            response.content,
            strict=True,
        )
    except (TypeError, ValueError, ValidationError):
        raise SmokeFailure(
            check="catalogue_list",
            classification="invalid_response_shape",
            http_status=response.status_code,
        ) from None

    if (
        catalogue.limit != DEFAULT_LIMIT
        or catalogue.offset != DEFAULT_OFFSET
        or len(catalogue.items) > catalogue.limit
        or response_keys(raw_payload) & FORBIDDEN_RESPONSE_FIELDS
        or any(
            color.stock_quantity <= 0
            for product in catalogue.items
            for color in product.colors
        )
    ):
        raise SmokeFailure(
            check="catalogue_list",
            classification="catalogue_contract_violation",
            http_status=response.status_code,
        )
    return catalogue


async def validate_internal_eligibility(
    *,
    authenticated_request: AuthenticatedRequestContext,
    catalogue: ProductListResponse,
) -> None:
    """Inspect hidden upstream fields without printing product data."""

    try:
        upstream_products = await app.state.catalogue_gateway.list_products(
            authenticated_request=authenticated_request,
            limit=DEFAULT_LIMIT,
            offset=DEFAULT_OFFSET,
        )
    except Exception:
        raise SmokeFailure(
            check="catalogue_eligibility",
            classification="catalogue_verification_failed",
        ) from None

    upstream_by_id = {product.id: product for product in upstream_products}
    for item in catalogue.items:
        source = upstream_by_id.get(item.id)
        if (
            source is None
            or not is_recommendation_eligible(source)
            or source.seller.approval_state != "approved"
            or not source.category.is_active
            or any(
                assignment.confirmation_state != "party_confirmed"
                for assignment in source.enrichment_assignments
            )
        ):
            raise SmokeFailure(
                check="catalogue_eligibility",
                classification="ineligible_product_returned",
            )


def random_missing_product_id(existing_ids: set[UUID]) -> UUID:
    candidate = uuid4()
    while candidate in existing_ids:
        candidate = uuid4()
    return candidate


async def count_eligible_source_rows(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    session: PasswordSession,
) -> None:
    """Report only aggregate source counts when the eligible catalogue is empty."""

    base_url = str(settings.supabase_url).rstrip("/")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {session.access_token.get_secret_value()}",
        "Prefer": "count=exact",
        "Range": "0-0",
        "apikey": settings.supabase_publishable_key.get_secret_value(),
    }
    checks = (
        (
            "published_product_count",
            "product",
            {"select": "id", "lifecycle_state": "eq.published"},
        ),
        (
            "approved_seller_count",
            "marketplace_party",
            {"select": "id", "approval_state": "eq.approved"},
        ),
        (
            "active_category_count",
            "category",
            {"select": "id", "is_active": "eq.true"},
        ),
        (
            "in_stock_color_count",
            "product_color",
            {"select": "id", "stock_quantity": "gt.0"},
        ),
    )

    for check, table, params in checks:
        try:
            response = await client.request(
                "HEAD",
                f"{base_url}/rest/v1/{table}",
                params=params,
                headers=headers,
                timeout=settings.supabase_auth_timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SmokeFailure(
                check=check,
                classification="catalogue_service_unavailable",
            ) from None

        if response.status_code not in {200, 206}:
            raise SmokeFailure(
                check=check,
                classification="catalogue_aggregate_check_failed",
                http_status=response.status_code,
            )
        content_range = response.headers.get("content-range", "")
        total = content_range.rpartition("/")[2]
        if not total.isdecimal():
            raise SmokeFailure(
                check=check,
                classification="invalid_aggregate_response",
                http_status=response.status_code,
            )
        report_result(
            check=check,
            status="passed",
            http_status=response.status_code,
            product_count=int(total),
        )


async def run_live_checks(
    *,
    settings: Settings,
    session: PasswordSession,
) -> None:
    access_token = session.access_token.get_secret_value()
    request_headers = {"Authorization": f"Bearer {access_token}"}

    async with app.router.lifespan_context(app):
        api_transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=api_transport,
            base_url="http://testserver",
        ) as api_client:
            health_response = await api_client.get("/health")
            validate_health(health_response)
            report_result(
                check="health",
                status="passed",
                http_status=health_response.status_code,
            )

            me_response = await api_client.get("/v1/me", headers=request_headers)
            current_user = validate_me(me_response)
            report_result(
                check="current_user",
                status="passed",
                http_status=me_response.status_code,
            )

            list_response = await api_client.get(
                "/v1/catalog/products",
                params={"limit": DEFAULT_LIMIT, "offset": DEFAULT_OFFSET},
                headers=request_headers,
            )
            catalogue = validate_catalogue(list_response)
            report_result(
                check="catalogue_list",
                status="passed",
                http_status=list_response.status_code,
                product_count=len(catalogue.items),
            )

            authenticated_request = AuthenticatedRequestContext(
                user_id=current_user.user_id,
                access_token=session.access_token,
            )
            await validate_internal_eligibility(
                authenticated_request=authenticated_request,
                catalogue=catalogue,
            )
            report_result(check="catalogue_eligibility", status="passed")

            if catalogue.items:
                product_id = catalogue.items[0].id
                detail_response = await api_client.get(
                    f"/v1/catalog/products/{product_id}",
                    headers=request_headers,
                )
                require_status(
                    detail_response,
                    check="catalogue_detail",
                    expected_status=200,
                )
                try:
                    detail = ProductResponse.model_validate_json(
                        detail_response.content,
                        strict=True,
                    )
                except ValidationError:
                    raise SmokeFailure(
                        check="catalogue_detail",
                        classification="invalid_response_shape",
                        http_status=detail_response.status_code,
                    ) from None
                if detail.id != product_id:
                    raise SmokeFailure(
                        check="catalogue_detail",
                        classification="product_identity_mismatch",
                        http_status=detail_response.status_code,
                    )
                report_result(
                    check="catalogue_detail",
                    status="passed",
                    http_status=detail_response.status_code,
                )
            else:
                async with httpx.AsyncClient() as count_client:
                    await count_eligible_source_rows(
                        client=count_client,
                        settings=settings,
                        session=session,
                    )
            missing_product_id = random_missing_product_id(
                {product.id for product in catalogue.items}
            )
            missing_response = await api_client.get(
                f"/v1/catalog/products/{missing_product_id}",
                headers=request_headers,
            )
            require_status(
                missing_response,
                check="missing_product",
                expected_status=404,
            )
            try:
                missing_payload = missing_response.json()
            except ValueError:
                missing_payload = None
            if missing_payload != {
                "detail": {
                    "code": "product_not_found",
                    "message": "The product was not found.",
                }
            }:
                raise SmokeFailure(
                    check="missing_product",
                    classification="invalid_safe_error",
                    http_status=missing_response.status_code,
                )
            report_result(
                check="missing_product",
                status="passed",
                http_status=missing_response.status_code,
                classification="product_not_found",
            )

    del access_token
    del request_headers


async def async_main() -> None:
    try:
        settings = load_settings()
    except RuntimeError:
        raise SmokeFailure(
            check="configuration",
            classification="invalid_configuration",
        ) from None

    email, password = collect_credentials()
    logging.getLogger("httpx").disabled = True
    logging.getLogger("httpcore").disabled = True

    async with httpx.AsyncClient() as auth_client:
        session, auth_status = await sign_in(
            client=auth_client,
            settings=settings,
            email=email,
            password=password,
        )
    del email
    del password

    report_result(
        check="password_authentication",
        status="passed",
        http_status=auth_status,
    )
    await run_live_checks(settings=settings, session=session)
    del session


def main() -> int:
    try:
        asyncio.run(async_main())
    except SmokeFailure as failure:
        report_result(
            check=failure.check,
            status="failed",
            http_status=failure.http_status,
            classification=failure.classification,
        )
        return 1
    except KeyboardInterrupt:
        report_result(
            check="credential_input",
            status="failed",
            classification="credential_input_cancelled",
        )
        return 1
    except Exception:
        report_result(
            check="live_smoke",
            status="failed",
            classification="unexpected_internal_error",
        )
        return 1
    return 0


def _exit() -> NoReturn:
    raise SystemExit(main())


if __name__ == "__main__":
    _exit()
