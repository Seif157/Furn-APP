"""Real products like one the customer is looking at.

Deterministic and grounded like the rest of Phase 6. Similar means the same
kind of furniture first, then shared catalogue facts: the same material, a
colour in common, a confirmed style, a price and width close to this one. Each
suggestion names the facts it shares, so nothing is called "similar" on a
feeling.

The product itself, anything out of stock, and anything of another kind are
never suggested. A sofa page that suggests chairs is not showing similar
products, it is showing different ones.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.catalog.normalization import COLOURS, MATERIALS, NormalizedProduct
from app.recommendations.explanations import format_money
from app.recommendations.models import ReasonResponse
from app.search.localization import response_language, term_label
from app.search.models import Language

DEFAULT_SIMILAR = 6
MAX_SIMILAR = 12
NEAR_PRICE = Decimal("0.15")
"""Within 15% of this product's price counts as a similar price."""
NEAR_WIDTH_CM = Decimal(10)


@dataclass(frozen=True, slots=True)
class Similar:
    product: NormalizedProduct
    score: Decimal
    price_difference: Decimal
    """Candidate's price minus this product's; negative means cheaper."""
    shared_materials: tuple[str, ...]
    shared_colours: tuple[str, ...]
    shared_styles: tuple[str, ...]
    near_price: bool
    near_width: bool


def _same_kind(target: NormalizedProduct, other: NormalizedProduct) -> bool:
    if target.category.slug is not None:
        return other.category.slug == target.category.slug
    return other.category.id == target.category.id


def _slugs(terms) -> set[str]:
    return {t.slug for t in terms if t.slug is not None}


def _styles(product: NormalizedProduct) -> set[str]:
    return {a.value_normalized for a in product.attributes if a.kind == "style"}


def find_similar(
    target: NormalizedProduct,
    candidates: Iterable[NormalizedProduct],
    *,
    limit: int = DEFAULT_SIMILAR,
) -> tuple[Similar, ...]:
    found: list[Similar] = []
    target_materials = _slugs(target.materials)
    target_colours = _slugs(c for c in target.colours if c.stock_quantity > 0)
    target_styles = _styles(target)

    for other in candidates:
        if other.id == target.id or not _same_kind(target, other):
            continue
        in_stock = [c for c in other.colours if c.stock_quantity > 0]
        if not in_stock:
            continue

        materials = tuple(sorted(target_materials & _slugs(other.materials)))
        colours = tuple(sorted(target_colours & _slugs(in_stock)))
        styles = tuple(sorted(target_styles & _styles(other)))
        difference = other.effective_price - target.effective_price
        relative = (
            abs(difference) / target.effective_price
            if target.effective_price > 0
            else Decimal(1)
        )
        near_price = relative <= NEAR_PRICE
        near_width = (
            target.width_cm is not None
            and other.width_cm is not None
            and abs(other.width_cm - target.width_cm) <= NEAR_WIDTH_CM
        )

        score = (
            2 * len(materials)
            + len(colours)
            + 2 * len(styles)
            # Price closeness is continuous so two otherwise equal products
            # are ordered by how close they are, not by id.
            + 3 * max(Decimal(0), 1 - relative)
            + (1 if near_width else 0)
        )
        found.append(
            Similar(
                product=other,
                score=score.quantize(Decimal("0.0001")),
                price_difference=difference,
                shared_materials=materials,
                shared_colours=colours,
                shared_styles=styles,
                near_price=near_price,
                near_width=near_width,
            )
        )

    found.sort(key=lambda s: (-s.score, abs(s.price_difference), str(s.product.id)))
    return tuple(found[:limit])


def similar_reasons(item: Similar, language: Language) -> tuple[ReasonResponse, ...]:
    """The shared facts, each stated as the catalogue holds it."""

    arabic = response_language(language) == "ar"
    reasons: list[ReasonResponse] = []

    if item.shared_materials:
        names = [term_label(MATERIALS, s, language) for s in item.shared_materials]
        joined = "، ".join(names) if arabic else ", ".join(names)
        reasons.append(
            ReasonResponse(
                code="material",
                text=f"نفس الخامة: {joined}" if arabic else f"Same material: {joined}",
            )
        )
    if item.shared_colours:
        names = [term_label(COLOURS, s, language) for s in item.shared_colours]
        joined = "، ".join(names) if arabic else ", ".join(names)
        reasons.append(
            ReasonResponse(
                code="colour",
                text=f"متاح كمان بلون {joined}" if arabic else f"Also in {joined}",
            )
        )
    if item.shared_styles:
        joined = ", ".join(item.shared_styles)
        reasons.append(
            ReasonResponse(
                code="style",
                text=f"نفس الستايل: {joined}" if arabic else f"Same style: {joined}",
            )
        )

    difference = item.price_difference
    amount = format_money(abs(difference), language)
    if difference == 0:
        text = "بنفس السعر" if arabic else "Same price"
    elif difference < 0:
        text = f"أرخص بـ {amount}" if arabic else f"{amount} cheaper"
    else:
        text = f"أغلى بـ {amount}" if arabic else f"{amount} more"
    reasons.append(ReasonResponse(code="price", text=text))

    if item.near_width and item.product.width_cm is not None:
        width = item.product.width_cm.normalize()
        shown = f"{int(width)}" if width == width.to_integral_value() else f"{width:f}"
        reasons.append(
            ReasonResponse(
                code="width",
                text=f"مقاس قريب: عرض {shown} سم"
                if arabic
                else f"Similar size: {shown} cm wide",
            )
        )
    return tuple(reasons)
