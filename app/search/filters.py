"""Hard-constraint evaluation over normalized products (Phase 4D).

Every check is explicit and reports the value it compared, so a caller can
explain why a product was excluded without re-deriving the rule. A product
whose dimension is unknown fails a dimension constraint: the catalogue cannot
prove the fit, so the product is not offered as fitting.
"""

from __future__ import annotations

from decimal import Decimal

from app.catalog.normalization import NormalizedProduct
from app.search.models import DimensionRange, HardConstraints, PriceRange
from app.search.results import ConstraintCheck


def _within(value: Decimal, minimum: Decimal | None, maximum: Decimal | None) -> bool:
    if minimum is not None and value < minimum:
        return False
    return not (maximum is not None and value > maximum)


def _price_check(
    product: NormalizedProduct, price: PriceRange | None
) -> ConstraintCheck:
    observed = str(product.effective_price)
    if price is None:
        return ConstraintCheck(name="price", satisfied=True, observed=observed)
    return ConstraintCheck(
        name="price",
        satisfied=_within(product.effective_price, price.minimum, price.maximum),
        observed=observed,
    )


def _dimension_check(
    name: str, value: Decimal | None, bounds: DimensionRange | None
) -> ConstraintCheck:
    observed = None if value is None else str(value)
    if bounds is None:
        return ConstraintCheck(name=name, satisfied=True, observed=observed)  # type: ignore[arg-type]
    satisfied = value is not None and _within(
        value, bounds.minimum_cm, bounds.maximum_cm
    )
    return ConstraintCheck(name=name, satisfied=satisfied, observed=observed)  # type: ignore[arg-type]


def constraint_checks(
    product: NormalizedProduct, hard: HardConstraints
) -> tuple[ConstraintCheck, ...]:
    """Evaluate every hard constraint; unconstrained checks are satisfied."""

    in_stock_colours = tuple(c for c in product.colours if c.stock_quantity > 0)
    considered = in_stock_colours if hard.in_stock_only else product.colours
    colour_slugs = {c.slug for c in considered if c.slug is not None}
    material_slugs = {m.slug for m in product.materials if m.slug is not None}

    return (
        ConstraintCheck(
            name="category",
            satisfied=hard.category is None or product.category.slug == hard.category,
            observed=product.category.slug,
        ),
        ConstraintCheck(
            name="colours",
            satisfied=not hard.colours or bool(colour_slugs & set(hard.colours)),
            observed=",".join(sorted(colour_slugs)) or None,
        ),
        ConstraintCheck(
            name="materials",
            satisfied=set(hard.materials) <= material_slugs,
            observed=",".join(sorted(material_slugs)) or None,
        ),
        _price_check(product, hard.price),
        _dimension_check("width", product.width_cm, hard.width),
        _dimension_check("height", product.height_cm, hard.height),
        _dimension_check("depth", product.depth_cm, hard.depth),
        ConstraintCheck(
            name="in_stock",
            satisfied=not hard.in_stock_only or bool(in_stock_colours),
            observed=str(sum(c.stock_quantity for c in product.colours)),
        ),
    )


def satisfies_all(checks: tuple[ConstraintCheck, ...]) -> bool:
    return all(check.satisfied for check in checks)
