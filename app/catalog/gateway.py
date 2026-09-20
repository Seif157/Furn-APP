"""Asynchronous read-only gateway to the Supabase PostgREST catalogue."""

from typing import Protocol
from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from app.auth.models import AuthenticatedRequestContext
from app.catalog.upstream_models import UpstreamProduct
from app.config import Settings

CATALOG_ROOT_SELECT = (
    "id,name,description,price,discount_price,"
    "width:width_cm,height:height_cm,depth:depth_cm,weight:weight_kg,"
    "materials,lifecycle_state"
)
CATALOG_ENRICHMENT_SELECT = (
    "enrichment_assignments:product_enrichment_assignment!"
    "product_enrichment_assignment_product_fk("
    "attribute_id,confirmation_state,"
    "attribute:product_enrichment_attribute!"
    "product_enrichment_assignment_attribute_fk("
    "id,kind:attribute_kind,value:attribute_value"
    ")"
    ")"
)
CATALOG_SELECT = (
    f"{CATALOG_ROOT_SELECT},"
    "category:category!inner(id,name,is_active),"
    "seller:marketplace_party!inner(id,business_name,approval_state),"
    "colors:product_color!inner(id,color_value,stock_quantity,display_order),"
    "images:product_image(id,image_url,is_primary,display_order,product_color_id),"
    f"{CATALOG_ENRICHMENT_SELECT}"
)

_PRODUCTS_ADAPTER = TypeAdapter(tuple[UpstreamProduct, ...])


def catalogue_query_params() -> dict[str, str]:
    """Build the exact filtered and deterministically ordered production query."""

    return {
        "select": CATALOG_SELECT,
        "lifecycle_state": "eq.published",
        "seller.approval_state": "eq.approved",
        "category.is_active": "eq.true",
        "colors.stock_quantity": "gt.0",
        "enrichment_assignments.confirmation_state": "eq.party_confirmed",
        "order": "id.asc",
        "colors.order": "display_order.asc,id.asc",
        "images.order": "is_primary.desc,display_order.asc,id.asc",
        "enrichment_assignments.order": "attribute_id.asc",
    }


class CatalogueUpstreamError(Exception):
    """Raised when PostgREST returns unusable data or a client error."""


class CatalogueServiceUnavailableError(Exception):
    """Raised when the Supabase catalogue service is unavailable."""


class CatalogueGateway(Protocol):
    """Interface consumed by the catalogue router."""

    async def list_products(
        self,
        *,
        authenticated_request: AuthenticatedRequestContext,
        limit: int,
        offset: int,
    ) -> tuple[UpstreamProduct, ...]:
        """Fetch one page plus a look-ahead product."""

    async def get_product(
        self,
        *,
        authenticated_request: AuthenticatedRequestContext,
        product_id: UUID,
    ) -> UpstreamProduct | None:
        """Fetch one eligible product by UUID."""

    async def list_by_ids(
        self,
        *,
        authenticated_request: AuthenticatedRequestContext,
        product_ids: tuple[UUID, ...],
    ) -> tuple[UpstreamProduct, ...]:
        """Fetch the eligible products among these ids, in catalogue order."""


class SupabaseCatalogueGateway:
    """Retrieve explicitly filtered product records through PostgREST."""

    def __init__(self, *, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._products_endpoint = (
            f"{str(settings.supabase_url).rstrip('/')}/rest/v1/product"
        )
        self._publishable_key = settings.supabase_publishable_key.get_secret_value()
        self._timeout_seconds = settings.supabase_auth_timeout_seconds

    async def list_products(
        self,
        *,
        authenticated_request: AuthenticatedRequestContext,
        limit: int,
        offset: int,
    ) -> tuple[UpstreamProduct, ...]:
        params = catalogue_query_params()
        params.update(
            {
                "limit": str(limit + 1),
                "offset": str(offset),
            }
        )
        return await self._request_products(
            authenticated_request=authenticated_request,
            params=params,
        )

    async def get_product(
        self,
        *,
        authenticated_request: AuthenticatedRequestContext,
        product_id: UUID,
    ) -> UpstreamProduct | None:
        params = catalogue_query_params()
        params.update(
            {
                "id": f"eq.{product_id}",
                "limit": "1",
            }
        )
        products = await self._request_products(
            authenticated_request=authenticated_request,
            params=params,
        )
        return products[0] if products else None

    async def list_by_ids(
        self,
        *,
        authenticated_request: AuthenticatedRequestContext,
        product_ids: tuple[UUID, ...],
    ) -> tuple[UpstreamProduct, ...]:
        """Fetch several products at once, under the same eligibility filters.

        Used to look up products a customer already bought. An id that is no
        longer published, or never was visible to this caller, simply does not
        come back, which is the same answer the catalogue endpoints give.
        """

        if not product_ids:
            return ()
        params = catalogue_query_params()
        identifiers = ",".join(str(product_id) for product_id in product_ids)
        params.update({"id": f"in.({identifiers})", "limit": str(len(product_ids))})
        return await self._request_products(
            authenticated_request=authenticated_request,
            params=params,
        )

    async def _request_products(
        self,
        *,
        authenticated_request: AuthenticatedRequestContext,
        params: dict[str, str],
    ) -> tuple[UpstreamProduct, ...]:
        try:
            response = await self._client.get(
                self._products_endpoint,
                params=params,
                headers={
                    "Accept": "application/json",
                    "apikey": self._publishable_key,
                    "Authorization": (
                        "Bearer "
                        f"{authenticated_request.access_token.get_secret_value()}"
                    ),
                },
                timeout=self._timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise CatalogueServiceUnavailableError from None

        if response.status_code >= 500 or response.status_code == 429:
            raise CatalogueServiceUnavailableError
        if response.status_code != httpx.codes.OK:
            raise CatalogueUpstreamError

        try:
            return _PRODUCTS_ADAPTER.validate_json(response.content, strict=True)
        except ValidationError:
            raise CatalogueUpstreamError from None
