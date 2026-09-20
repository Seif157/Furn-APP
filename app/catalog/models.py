"""Strict public response models for catalogue endpoints."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl, JsonValue


class StrictResponseModel(BaseModel):
    """Base configuration shared by immutable catalogue response models."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        strict=True,
    )


class CategoryResponse(StrictResponseModel):
    id: UUID
    name: str


class SellerResponse(StrictResponseModel):
    id: UUID
    business_name: str


class ProductColorResponse(StrictResponseModel):
    id: UUID
    value: str
    stock_quantity: int
    display_order: int


class ProductImageResponse(StrictResponseModel):
    id: UUID
    url: HttpUrl
    is_primary: bool
    display_order: int
    color_id: UUID | None


class EnrichmentAttributeResponse(StrictResponseModel):
    kind: str
    value: JsonValue


class ProductResponse(StrictResponseModel):
    id: UUID
    name: str
    description: str | None
    price: Decimal
    discount_price: Decimal | None
    width: Decimal | None
    height: Decimal | None
    depth: Decimal | None
    weight: Decimal | None
    materials: tuple[str, ...]
    category: CategoryResponse
    seller: SellerResponse
    colors: tuple[ProductColorResponse, ...]
    images: tuple[ProductImageResponse, ...]
    enrichment_attributes: tuple[EnrichmentAttributeResponse, ...]


class ProductListResponse(StrictResponseModel):
    items: tuple[ProductResponse, ...]
    limit: int
    offset: int
    has_more: bool
