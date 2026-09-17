"""Nearest real alternatives when nothing matched (Phase 6.10).

An empty result that says only "nothing found" is a dead end. Section 6.10
allows offering the nearest real alternatives and forbids fabricating a
product, so these are catalogue rows chosen by how close they came, never
anything invented.

Closeness is counted, not guessed: the fewest failed hard constraints wins,
then the cheaper product, then the product id so the order is total and
stable. A customer who asked for a beech sofa under 15,000 and sees "this one
is 800 over your budget" has something to decide about.

Three rules keep the offer honest.

Stock is never relaxed, because a sold-out row is not an alternative, it is a
broken promise.

Category is never relaxed either, and that one is worth stating. Counting
misses alone makes a 1,200 EGP chair the closest thing to a sofa under 5,000,
because the chair fails only the category while every sofa fails only the
price, and the chair is cheaper so it sorts first. It is arithmetically the
nearest and obviously the wrong answer. Naming a category is the strongest
statement of intent a customer makes, so an alternative stays inside it. When
nothing in that category comes close, the honest result is no alternatives.

And a product failing most of what was asked is not shown at all; past a
threshold it stops being an alternative and becomes a random product.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.catalog.normalization import NormalizedProduct
from app.search.filters import constraint_checks
from app.search.models import SearchSpecification
from app.search.results import ConstraintCheck

MAX_ALTERNATIVES = 3
MAX_MISSED = 2
"""Beyond this many failed constraints a product is not a near miss."""

# Relaxing stock offers something the customer cannot buy; relaxing category
# offers something they did not ask for. Neither is an alternative.
NEVER_RELAXED = frozenset({"in_stock", "category"})


class Alternative:
    """A near miss and the checks explaining it."""

    __slots__ = ("product", "checks", "missed")

    def __init__(
        self, product: NormalizedProduct, checks: tuple[ConstraintCheck, ...]
    ) -> None:
        self.product = product
        self.checks = checks
        self.missed = tuple(check for check in checks if not check.satisfied)


def nearest_alternatives(
    products: Iterable[NormalizedProduct],
    specification: SearchSpecification,
    *,
    limit: int = MAX_ALTERNATIVES,
) -> tuple[Alternative, ...]:
    """Return the closest real products, or nothing when none came close.

    Only meaningful when the search itself matched nothing; a search with
    results should show those instead.
    """

    candidates: list[Alternative] = []
    for product in products:
        checks = constraint_checks(product, specification.hard)
        alternative = Alternative(product, checks)
        missed_names = {check.name for check in alternative.missed}
        if not missed_names:
            # It matched after all, so it is a result and not an alternative.
            continue
        if missed_names & NEVER_RELAXED:
            continue
        if len(alternative.missed) > MAX_MISSED:
            continue
        candidates.append(alternative)

    candidates.sort(
        key=lambda item: (
            len(item.missed),
            item.product.effective_price,
            item.product.id.int,
        )
    )
    return tuple(candidates[:limit])
