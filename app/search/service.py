"""Deterministic structured search over normalized products (Phase 4D).

Hard constraints are applied first and can only exclude. Soft preferences only
order what remains. The order is total and stable: score descending, then
effective price ascending, then product id, so the same inputs always give the
same page. No AI provider and no database are involved.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from app.catalog.normalization import NormalizedProduct
from app.search.filters import constraint_checks, satisfies_all
from app.search.models import SearchSpecification
from app.search.ranking import combine, score_parts
from app.search.results import ScoredProduct, SearchResults

MAX_CANDIDATES = 10_000


def search_products(
    products: Iterable[NormalizedProduct],
    specification: SearchSpecification,
) -> SearchResults:
    """Filter, score, order, and page a bounded sequence of candidates."""

    candidates = list(products)
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError("too many candidates for in-memory structured search")
    seen: set = set()
    for product in candidates:
        if product.id in seen:
            raise ValueError("duplicate product id among candidates")
        seen.add(product.id)

    rejections: Counter[str] = Counter()
    matches: list[ScoredProduct] = []
    for product in candidates:
        checks = constraint_checks(product, specification.hard)
        if not satisfies_all(checks):
            for check in checks:
                if not check.satisfied:
                    rejections[check.name] += 1
            continue
        parts = score_parts(product, specification.soft, specification.query)
        matches.append(
            ScoredProduct(
                product_id=product.id,
                score=combine(parts),
                parts=parts,
                checks=checks,
                effective_price=product.effective_price,
            )
        )

    matches.sort(
        key=lambda item: (-item.score, item.effective_price, item.product_id.int)
    )
    page = tuple(matches[: specification.limit])
    return SearchResults(
        items=page,
        limit=specification.limit,
        has_more=len(matches) > specification.limit,
        candidate_count=len(candidates),
        match_count=len(matches),
        rejections=tuple(sorted(rejections.items())),  # type: ignore[arg-type]
        schema_version=1,
    )
