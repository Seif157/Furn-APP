"""Tests for grounded reasons and nearest alternatives (Phase 6).

Nothing here contacts a provider. Every string a customer reads is built from
a catalogue value, which is the property these tests defend.
"""

from decimal import Decimal

import pytest
from pydantic import TypeAdapter

from app.catalog import normalization as norm
from app.catalog.transform import is_recommendation_eligible
from app.catalog.upstream_models import UpstreamProduct
from app.recommendations.alternatives import MAX_MISSED, nearest_alternatives
from app.recommendations.explanations import match_reasons, shortfall_reasons
from app.search import models
from app.search import service as search_service
from app.search.filters import constraint_checks
from tests import seed_catalogue as seed

ADAPTER = TypeAdapter(tuple[UpstreamProduct, ...])


def eligible_catalogue() -> tuple[norm.NormalizedProduct, ...]:
    products = ADAPTER.validate_json(seed.as_json_fixture(), strict=True)
    return tuple(
        norm.normalize_product(product)
        for product in products
        if is_recommendation_eligible(product)
    )


def sofa_under(maximum: str, *, width: str | None = None) -> models.SearchSpecification:
    return models.build_specification(
        category="sofa",
        price=models.PriceRange(maximum=Decimal(maximum)),
        width=(
            models.DimensionRange(maximum_cm=Decimal(width))
            if width is not None
            else None
        ),
    ).specification


# --- reasons are catalogue facts --------------------------------------------


def test_a_reason_quotes_the_product_value_and_the_stated_limit() -> None:
    catalogue = eligible_catalogue()
    spec = sofa_under("30000", width="220")
    results = search_service.search_products(catalogue, spec)
    top = results.items[0]
    product = next(p for p in catalogue if p.id == top.product_id)

    reasons = match_reasons(top.checks, spec.hard, "en")
    text = {reason.code: reason.text for reason in reasons}

    # The master plan's example: "fits your width limit because its catalogue
    # width is 218 cm". The number in the sentence is the product's own.
    assert str(int(product.width_cm)) in text["width"]
    assert "220 cm limit" in text["width"]
    assert str(int(product.effective_price)) in text["price"].replace(",", "")
    assert "30,000 EGP budget" in text["price"]
    assert text["in_stock"] == "in stock"


def test_reasons_are_written_in_the_customers_language() -> None:
    catalogue = eligible_catalogue()
    spec = sofa_under("30000", width="220")
    results = search_service.search_products(catalogue, spec)

    arabic = {
        r.code: r.text for r in match_reasons(results.items[0].checks, spec.hard, "ar")
    }

    assert arabic["in_stock"] == "متوفر"
    assert "جنيه" in arabic["price"]
    assert "سم" in arabic["width"]
    assert "EGP" not in arabic["price"]


def test_only_stated_constraints_produce_a_reason() -> None:
    catalogue = eligible_catalogue()
    # Category only: no budget and no size were stated.
    spec = models.build_specification(category="sofa").specification
    results = search_service.search_products(catalogue, spec)

    codes = {r.code for r in match_reasons(results.items[0].checks, spec.hard, "en")}

    assert "category" in codes
    assert "in_stock" in codes
    # Saying "within your budget" when no budget was given would be noise.
    assert "price" not in codes
    assert "width" not in codes


def test_a_shortfall_states_how_far_off_the_product_is() -> None:
    catalogue = eligible_catalogue()
    spec = sofa_under("10000")
    over_budget = next(
        product
        for product in catalogue
        if product.category.slug == "sofas"
        and product.effective_price > Decimal("10000")
    )

    reasons = shortfall_reasons(
        constraint_checks(over_budget, spec.hard), spec.hard, "en"
    )
    price_reason = next(r for r in reasons if r.code == "price")

    shortfall = over_budget.effective_price - Decimal("10000")
    assert str(int(shortfall)) in price_reason.text.replace(",", "")
    assert "over your budget" in price_reason.text


def test_an_arabic_shortfall_is_written_in_arabic() -> None:
    catalogue = eligible_catalogue()
    spec = sofa_under("10000")
    over_budget = next(
        product
        for product in catalogue
        if product.category.slug == "sofas"
        and product.effective_price > Decimal("10000")
    )

    reasons = shortfall_reasons(
        constraint_checks(over_budget, spec.hard), spec.hard, "ar"
    )

    assert any("ميزانيتك" in r.text for r in reasons)


# --- alternatives are real products -----------------------------------------


def test_nothing_matched_still_offers_the_closest_real_products() -> None:
    catalogue = eligible_catalogue()
    # No sofa is this cheap, so the budget is what excludes everything.
    spec = sofa_under("5000")
    results = search_service.search_products(catalogue, spec)
    assert results.match_count == 0

    alternatives = nearest_alternatives(catalogue, spec)

    assert alternatives
    catalogue_ids = {product.id for product in catalogue}
    for alternative in alternatives:
        # Every alternative is a row that exists; nothing is invented.
        assert alternative.product.id in catalogue_ids
        assert 1 <= len(alternative.missed) <= MAX_MISSED
    # Cheapest first among equally close products.
    prices = [a.product.effective_price for a in alternatives]
    assert prices == sorted(prices)


def test_an_alternative_is_never_out_of_stock() -> None:
    catalogue = eligible_catalogue()
    spec = models.build_specification(
        category="sofa",
        colours=("navy",),
        price=models.PriceRange(maximum=Decimal("1")),
    ).specification

    for alternative in nearest_alternatives(catalogue, spec):
        assert all(
            check.satisfied for check in alternative.checks if check.name == "in_stock"
        )


def test_a_product_missing_almost_everything_is_not_an_alternative() -> None:
    catalogue = eligible_catalogue()
    # Wrong category, impossible budget, impossible size: three misses.
    spec = models.build_specification(
        category="sofa",
        price=models.PriceRange(maximum=Decimal("1")),
        width=models.DimensionRange(maximum_cm=Decimal("1")),
    ).specification

    alternatives = nearest_alternatives(catalogue, spec)

    # Past a couple of misses it stops being an alternative and becomes a
    # random product, so nothing qualifies here.
    assert all(len(a.missed) <= MAX_MISSED for a in alternatives)


def test_alternatives_are_empty_when_the_search_succeeded() -> None:
    catalogue = eligible_catalogue()
    spec = sofa_under("30000")
    results = search_service.search_products(catalogue, spec)
    assert results.match_count > 0

    # A product that matched is a result, never an alternative.
    matched_ids = {item.product_id for item in results.items}
    for alternative in nearest_alternatives(catalogue, spec):
        assert alternative.product.id not in matched_ids


@pytest.mark.parametrize("language", ["ar", "en"])
def test_every_reason_is_non_empty_text(language: str) -> None:
    catalogue = eligible_catalogue()
    spec = sofa_under("15000", width="220")
    results = search_service.search_products(catalogue, spec)

    for item in results.items:
        for reason in match_reasons(item.checks, spec.hard, language):  # type: ignore[arg-type]
            assert reason.text.strip()
            assert reason.code


def test_a_cheaper_product_from_another_category_is_never_an_alternative() -> None:
    # The arithmetic trap: asked for a sofa under 5,000, every sofa fails only
    # the price and every chair fails only the category, so counting misses
    # alone makes a 1,200 EGP chair the "nearest" answer. Naming a category is
    # the strongest statement of intent a customer makes, so it is never
    # relaxed.
    catalogue = eligible_catalogue()
    spec = sofa_under("5000")

    alternatives = nearest_alternatives(catalogue, spec)

    assert alternatives
    for alternative in alternatives:
        assert alternative.product.category.slug == "sofas"
        assert {check.name for check in alternative.missed} == {"price"}


@pytest.mark.parametrize("category", ["wardrobes", "beds", "dining", "chairs"])
def test_alternatives_always_stay_inside_the_requested_category(
    category: str,
) -> None:
    catalogue = eligible_catalogue()
    # A budget nothing can meet, so every candidate is a near miss on price.
    spec = models.build_specification(
        category=category, price=models.PriceRange(maximum=Decimal("100"))
    ).specification

    alternatives = nearest_alternatives(catalogue, spec)

    assert alternatives
    for alternative in alternatives:
        assert alternative.product.category.slug == category


def test_an_unresolvable_category_leaves_no_category_constraint() -> None:
    # "coffee table" does not resolve, so the specification carries no
    # category at all and there is nothing for alternatives to stay inside.
    build = models.build_specification(
        category="coffee table", price=models.PriceRange(maximum=Decimal("100"))
    )

    assert build.specification.hard.category is None
    assert build.unresolved[0].surface == "coffee table"
    # Every candidate then misses on price alone, which is a true statement
    # about the catalogue rather than a pretend match.
    for alternative in nearest_alternatives(eligible_catalogue(), build.specification):
        assert {check.name for check in alternative.missed} == {"price"}
