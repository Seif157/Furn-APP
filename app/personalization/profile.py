"""What this customer has bought before, as a small, honest profile.

Phase 9B. Personalization here is deliberately weak and deliberately visible.
Weak, because a customer who searches for a beech bed wants a beech bed, not
the sofa they bought last year: the profile can only break ties among products
that already satisfy every stated constraint. Visible, because reordering
someone's results on the strength of their own history is something they should
be told about, so the response says when it happened and why.

The profile is built from the caller's own orders, read with the caller's own
token, so row-level security decides what it can see. It is never stored, never
shared between users, and never leaves the process.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from app.catalog.normalization import NormalizedProduct

MIN_PURCHASES = 2
"""One purchase is an accident; two is the beginning of a taste."""

MAX_SLUGS = 3
"""Per dimension. A profile that likes everything prefers nothing."""


@dataclass(frozen=True, slots=True)
class TasteProfile:
    """Aggregate, per-customer, in memory only."""

    categories: frozenset[str] = frozenset()
    colours: frozenset[str] = frozenset()
    materials: frozenset[str] = frozenset()
    typical_price: Decimal | None = None
    """The median of what they actually paid, when there is enough to tell."""
    purchases: int = 0
    bought_product_ids: frozenset[UUID] = field(default_factory=frozenset)

    @property
    def is_useful(self) -> bool:
        """True when there is enough here to justify reordering anything."""

        return self.purchases >= MIN_PURCHASES and bool(
            self.categories or self.colours or self.materials or self.typical_price
        )


def _top(counter: Counter[str]) -> frozenset[str]:
    return frozenset(slug for slug, _count in counter.most_common(MAX_SLUGS))


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def build_profile(
    purchased: tuple[NormalizedProduct, ...],
    *,
    prices_paid: tuple[Decimal, ...] = (),
) -> TasteProfile:
    """Summarise what a customer bought into the few signals worth keeping.

    ``prices_paid`` comes from the order lines rather than the catalogue,
    because what they paid is what they chose; today's price may be a discount
    they never saw.
    """

    categories: Counter[str] = Counter()
    colours: Counter[str] = Counter()
    materials: Counter[str] = Counter()
    for product in purchased:
        if product.category.slug:
            categories[product.category.slug] += 1
        for colour in product.colours:
            if colour.slug:
                colours[colour.slug] += 1
        for material in product.materials:
            if material.slug:
                materials[material.slug] += 1

    usable_prices = [price for price in prices_paid if price > 0]
    return TasteProfile(
        categories=_top(categories),
        colours=_top(colours),
        materials=_top(materials),
        typical_price=_median(usable_prices),
        purchases=max(len(purchased), len(usable_prices)),
        bought_product_ids=frozenset(product.id for product in purchased),
    )
