"""Defensive eligibility filtering and stable catalogue response composition."""

import json

from app.catalog.models import (
    CategoryResponse,
    EnrichmentAttributeResponse,
    ProductColorResponse,
    ProductImageResponse,
    ProductListResponse,
    ProductResponse,
    SellerResponse,
)
from app.catalog.upstream_models import UpstreamProduct


def is_recommendation_eligible(product: UpstreamProduct) -> bool:
    """Recheck every catalogue rule independently of RLS and PostgREST filters."""

    return (
        product.lifecycle_state == "published"
        and product.seller.approval_state == "approved"
        and product.category.is_active
        and any(color.stock_quantity > 0 for color in product.colors)
    )


def build_product_response(product: UpstreamProduct) -> ProductResponse | None:
    """Remove ineligible/private data and deterministically order child records."""

    if not is_recommendation_eligible(product):
        return None

    colors = tuple(
        ProductColorResponse(
            id=color.id,
            value=color.color_value,
            stock_quantity=color.stock_quantity,
            display_order=color.display_order,
        )
        for color in sorted(
            (color for color in product.colors if color.stock_quantity > 0),
            key=lambda color: (color.display_order, color.id.int),
        )
    )
    images = tuple(
        ProductImageResponse(
            id=image.id,
            url=image.image_url,
            is_primary=image.is_primary,
            display_order=image.display_order,
            color_id=image.product_color_id,
        )
        for image in sorted(
            product.images,
            key=lambda image: (
                not image.is_primary,
                image.display_order,
                image.id.int,
            ),
        )
    )
    confirmed_assignments = (
        assignment
        for assignment in product.enrichment_assignments
        if assignment.confirmation_state == "party_confirmed"
    )
    enrichment_attributes = tuple(
        EnrichmentAttributeResponse(
            kind=assignment.attribute.kind,
            value=assignment.value,
        )
        for assignment in sorted(
            confirmed_assignments,
            key=lambda assignment: (
                assignment.attribute.kind,
                json.dumps(
                    assignment.value,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                assignment.id.int,
            ),
        )
    )

    return ProductResponse(
        id=product.id,
        name=product.name,
        description=product.description,
        price=product.price,
        discount_price=product.discount_price,
        width=product.width,
        height=product.height,
        depth=product.depth,
        weight=product.weight,
        materials=product.materials,
        category=CategoryResponse(
            id=product.category.id,
            name=product.category.name,
        ),
        seller=SellerResponse(
            id=product.seller.id,
            business_name=product.seller.business_name,
        ),
        colors=colors,
        images=images,
        enrichment_attributes=enrichment_attributes,
    )


def build_product_list_response(
    products: tuple[UpstreamProduct, ...],
    *,
    limit: int,
    offset: int,
) -> ProductListResponse:
    """Build a stable page and determine whether an eligible look-ahead exists."""

    eligible_products = tuple(
        response
        for response in (
            build_product_response(product)
            for product in sorted(products, key=lambda product: product.id.int)
        )
        if response is not None
    )
    return ProductListResponse(
        items=eligible_products[:limit],
        limit=limit,
        offset=offset,
        has_more=len(eligible_products) > limit,
    )
