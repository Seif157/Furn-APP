"""Strict internal models for the nested Supabase catalogue response."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue


class StrictUpstreamModel(BaseModel):
    """Reject unexpected or weakly typed PostgREST data."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        strict=True,
    )


class UpstreamCategory(StrictUpstreamModel):
    id: UUID
    name: str
    is_active: bool


class UpstreamSeller(StrictUpstreamModel):
    id: UUID
    business_name: str
    approval_state: Literal["pending", "approved", "rejected", "suspended"]


class UpstreamProductColor(StrictUpstreamModel):
    id: UUID
    color_value: str
    stock_quantity: int = Field(ge=0)
    display_order: int


class UpstreamProductImage(StrictUpstreamModel):
    id: UUID
    image_url: HttpUrl
    is_primary: bool
    display_order: int
    product_color_id: UUID | None


class UpstreamEnrichmentAttribute(StrictUpstreamModel):
    id: UUID
    kind: str
    value: JsonValue


class UpstreamEnrichmentAssignment(StrictUpstreamModel):
    attribute_id: UUID
    confirmation_state: Literal["ai_proposed", "party_confirmed"]
    attribute: UpstreamEnrichmentAttribute


class UpstreamProduct(StrictUpstreamModel):
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
    lifecycle_state: Literal["draft", "published", "hidden", "archived"]
    category: UpstreamCategory
    seller: UpstreamSeller
    colors: tuple[UpstreamProductColor, ...]
    images: tuple[UpstreamProductImage, ...]
    enrichment_assignments: tuple[UpstreamEnrichmentAssignment, ...]
