"""Tests binding the seed catalogue, its rendered SQL, and the search layers."""

import json
import re
from collections import Counter
from decimal import Decimal

from pglast import ast, parse_sql
from pydantic import TypeAdapter

from app.catalog import normalization as norm
from app.catalog.transform import is_recommendation_eligible
from app.catalog.upstream_models import UpstreamProduct
from app.search import models, service
from tests import seed_catalogue as seed

ADAPTER = TypeAdapter(tuple[UpstreamProduct, ...])


def upstream_seed() -> tuple[UpstreamProduct, ...]:
    return ADAPTER.validate_json(seed.as_json_fixture(), strict=True)


def normalized_seed() -> tuple[norm.NormalizedProduct, ...]:
    """Every seed row normalized, eligible or not."""

    return tuple(norm.normalize_product(product) for product in upstream_seed())


def eligible_catalogue() -> tuple[norm.NormalizedProduct, ...]:
    """What the API would hand to search: the same eligibility rule it applies."""

    return tuple(
        norm.normalize_product(product)
        for product in upstream_seed()
        if is_recommendation_eligible(product)
    )


def test_seed_shape_and_counts() -> None:
    products = seed.SEED_PRODUCTS
    assert len(products) == 44
    assert [p.number for p in products] == list(range(1, 45))
    assert sum(p.eligible for p in products) == 41  # 40 stocked + the no-dimension one
    assert Counter(p.category for p in products if p.number <= 40) == {
        "beds": 8,
        "dining": 8,
        "sofas": 8,
        "wardrobes": 8,
        "chairs": 8,
    }
    assert {p.lifecycle_state for p in products} == {"published", "draft", "hidden"}
    assert len({p.id for p in products}) == 44
    assert len({p.sku for p in products}) == 44
    assert all(p.sku.startswith("SEED-") for p in products)
    assert any(p.discount_price is not None for p in products)
    assert any(p.weight_kg is None for p in products)
    assert all(p.discount_price is None or p.discount_price < p.price for p in products)


def test_seed_follows_the_audited_catalogue_conventions() -> None:
    for product in seed.SEED_PRODUCTS:
        assert norm.has_arabic(product.name) and not norm.has_latin(product.name)
        assert norm.has_latin(product.description)
        assert " — " in seed.CATEGORY_LABELS[product.category]
        for colour in product.colours:
            assert " — " in seed.COLOUR_LABELS[colour.slug]
        for material in product.materials:
            assert material in seed.MATERIAL_TOKENS


def test_every_seed_product_normalizes_with_no_unmapped_terms() -> None:
    products = normalized_seed()
    assert len(products) == 44
    for product in products:
        assert product.category.slug is not None
        assert all(colour.slug is not None for colour in product.colours)
        assert all(material.slug is not None for material in product.materials)
        assert product.unmapped_terms == ()
    used_colours = {c.slug for p in products for c in p.colours}
    used_materials = {m.slug for p in products for m in p.materials}
    assert used_colours >= set(seed.COLOUR_LABELS)
    assert used_materials >= set(seed.MATERIAL_TOKENS)


def test_structured_search_over_the_seed_behaves_as_a_benchmark_should() -> None:
    catalogue = eligible_catalogue()
    assert len(catalogue) == 41
    spec = models.build_specification(
        category="كنب",
        price=models.PriceRange(maximum=Decimal("15000")),
        width=models.DimensionRange(maximum_cm=Decimal("220")),
        preferred_colours=("beige",),
        query="كنبة مودرن بيج",
        limit=10,
    ).specification
    results = service.search_products(catalogue, spec)
    assert results.candidate_count == 41
    # SEED-017, 019, 021, 022 fit price and width; SEED-024 fits only through
    # its discount, which proves the price check uses the effective price.
    assert results.match_count == 5
    # SEED-017 is the modern beige sofa: perfect colour and query overlap.
    assert results.items[0].product_id.hex.endswith("000000000017")
    assert results.items[0].score == Decimal("1")
    assert dict(results.rejections)["category"] == 33
    # The draft, hidden, and no-stock rows were removed by eligibility, so a
    # query-only specification matches every remaining row.
    everything = service.search_products(
        catalogue, models.build_specification(query="كنبة").specification
    )
    assert everything.match_count == 41
    assert everything.rejections == ()


def test_rendered_sql_is_byte_identical_and_guarded() -> None:
    assert seed.SEED_SQL_PATH.read_text(encoding="utf-8") == seed.render_seed_sql()
    assert seed.REMOVE_SQL_PATH.read_text(encoding="utf-8") == seed.render_remove_sql()
    for path in (seed.SEED_SQL_PATH, seed.REMOVE_SQL_PATH):
        statements = parse_sql(path.read_text(encoding="utf-8"))
        assert isinstance(statements[0].stmt, ast.TransactionStmt)
        assert isinstance(statements[-1].stmt, ast.TransactionStmt)
    seed_sql = seed.SEED_SQL_PATH.read_text(encoding="utf-8")
    assert "FAKE-DATA TESTING BRANCH ONLY" in seed_sql
    assert "seed products already exist" in seed_sql
    assert "seed requires an approved seller" in seed_sql
    assert seed_sql.count("INSERT INTO public.product (") == 1
    assert seed_sql.count("INSERT INTO public.product_color (") == 1
    assert seed_sql.count("INSERT INTO public.product_image (") == 1
    assert "UPDATE " not in seed_sql and "DELETE " not in seed_sql
    assert "service_role" not in seed_sql
    assert len(re.findall(r"'SEED-\d{3}'", seed_sql)) == 44
    assert seed_sql.count("placehold.co/800x600?text=SEED-") == 44
    remove_sql = seed.REMOVE_SQL_PATH.read_text(encoding="utf-8")
    assert remove_sql.count("sku LIKE 'SEED-%'") == 3
    assert "INSERT" not in remove_sql and "UPDATE " not in remove_sql
    # The seed lives outside sql/, which is reserved for reviewed migrations.
    assert seed.SEED_SQL_PATH.parent.name == "seed"


def test_json_fixture_round_trips_through_the_strict_upstream_model() -> None:
    payload = json.loads(seed.as_json_fixture())
    assert len(payload) == 44
    assert all(row["seller"]["approval_state"] == "approved" for row in payload)
    assert all(row["enrichment_assignments"] == [] for row in payload)
    assert all(row["images"][0]["image_url"].startswith("https://") for row in payload)
