"""Deterministic tests for Phase 4D structured search."""

import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from app.catalog import normalization as norm
from app.catalog.upstream_models import UpstreamProduct
from app.search import filters, models, ranking, service
from tests.test_catalog import product_payload

ADAPTER = TypeAdapter(UpstreamProduct)


def product(
    identifier: str,
    *,
    category: str = "Sofas — كنب",
    colours: tuple[tuple[str, int], ...] = (("بيج — beige", 2),),
    materials: tuple[str, ...] = ("خشب زان", "قماش"),
    price: float = 10000,
    discount_price: float | None = None,
    width: float | None = 220,
    height: float | None = 90,
    depth: float | None = 95,
    styles: tuple[str, ...] = (),
    room: str | None = None,
    name: str = "كنبة مودرن",
    description: str | None = "Modern sofa.",
) -> norm.NormalizedProduct:
    payload: dict[str, Any] = product_payload(
        f"{identifier}-0000-4000-8000-000000000000"
    )
    payload["name"] = name
    payload["description"] = description
    payload["price"] = price
    payload["discount_price"] = discount_price
    payload["width"] = width
    payload["height"] = height
    payload["depth"] = depth
    payload["weight"] = None
    payload["materials"] = list(materials)
    payload["category"]["name"] = category
    payload["colors"] = [
        {
            "id": f"5{index}000000-0000-4000-8000-000000000000",
            "color_value": value,
            "stock_quantity": stock,
            "display_order": index,
        }
        for index, (value, stock) in enumerate(colours)
    ]
    payload["images"] = []
    attributes = [("style", style) for style in styles]
    if room is not None:
        attributes.append(("room_type", room))
    payload["enrichment_assignments"] = [
        {
            "attribute_id": f"8{index}000000-0000-4000-8000-000000000000",
            "confirmation_state": "party_confirmed",
            "attribute": {
                "id": f"8{index}000000-0000-4000-8000-000000000000",
                "kind": kind,
                "value": value,
            },
        }
        for index, (kind, value) in enumerate(attributes)
    ]
    return norm.normalize_product(
        ADAPTER.validate_json(json.dumps(payload), strict=True)
    )


CATALOGUE = (
    product("10000000", styles=("modern",), room="living room"),
    product("20000000", price=35000, styles=("classic",)),
    product("30000000", colours=(("رمادي — grey", 0),), price=9000),
    product(
        "40000000",
        category="Beds — أسرّة",
        width=160,
        materials=("mdf",),
        name="سرير خشب",
    ),
    product("50000000", width=None, price=8000, discount_price=7000),
)


def spec(**kwargs: Any) -> models.SearchSpecification:
    return models.build_specification(**kwargs).specification


# --------------------------------------------------------------------------
# Hard filters
# --------------------------------------------------------------------------


def test_every_constraint_is_checked_and_unconstrained_checks_pass() -> None:
    checks = filters.constraint_checks(
        CATALOGUE[0], models.HardConstraints(category="sofas")
    )
    assert [c.name for c in checks] == [
        "category",
        "colours",
        "materials",
        "price",
        "width",
        "height",
        "depth",
        "in_stock",
    ]
    assert all(c.satisfied for c in checks)
    assert checks[0].observed == "sofas"
    assert checks[1].observed == "beige"
    assert checks[2].observed == "beech_wood,fabric"
    assert checks[3].observed == "10000"
    assert checks[7].observed == "2"


@pytest.mark.parametrize(
    ("hard", "failing"),
    [
        (models.HardConstraints(category="beds"), "category"),
        (models.HardConstraints(colours=("grey",)), "colours"),
        (models.HardConstraints(materials=("beech_wood", "mdf")), "materials"),
        (
            models.HardConstraints(price=models.PriceRange(maximum=Decimal("9999"))),
            "price",
        ),
        (
            models.HardConstraints(
                width=models.DimensionRange(maximum_cm=Decimal("200"))
            ),
            "width",
        ),
        (
            models.HardConstraints(
                height=models.DimensionRange(minimum_cm=Decimal("100"))
            ),
            "height",
        ),
        (
            models.HardConstraints(
                depth=models.DimensionRange(minimum_cm=Decimal("96"))
            ),
            "depth",
        ),
    ],
)
def test_each_hard_constraint_excludes_independently(
    hard: models.HardConstraints, failing: str
) -> None:
    checks = filters.constraint_checks(CATALOGUE[0], hard)
    assert [c.name for c in checks if not c.satisfied] == [failing]


def test_unknown_dimension_fails_a_dimension_constraint_but_passes_without_one() -> (
    None
):
    no_width = CATALOGUE[4]
    constrained = filters.constraint_checks(
        no_width,
        models.HardConstraints(width=models.DimensionRange(maximum_cm=Decimal("300"))),
    )
    assert [c.name for c in constrained if not c.satisfied] == ["width"]
    assert next(c for c in constrained if c.name == "width").observed is None
    assert filters.satisfies_all(
        filters.constraint_checks(no_width, models.HardConstraints())
    )


def test_stock_rules_respect_in_stock_only() -> None:
    out_of_stock = CATALOGUE[2]
    strict = filters.constraint_checks(
        out_of_stock, models.HardConstraints(colours=("grey",))
    )
    assert {c.name for c in strict if not c.satisfied} == {"colours", "in_stock"}
    lenient = filters.constraint_checks(
        out_of_stock, models.HardConstraints(colours=("grey",), in_stock_only=False)
    )
    assert filters.satisfies_all(lenient)


def test_price_constraint_uses_effective_price() -> None:
    discounted = CATALOGUE[4]
    checks = filters.constraint_checks(
        discounted,
        models.HardConstraints(price=models.PriceRange(maximum=Decimal("7500"))),
    )
    assert filters.satisfies_all(checks)
    assert next(c for c in checks if c.name == "price").observed == "7000"


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def test_score_is_zero_without_preferences_and_parts_only_for_expressed_ones() -> None:
    soft = models.SoftPreferences()
    assert ranking.score_parts(CATALOGUE[0], soft, None) == ()
    assert ranking.combine(()) == Decimal("0")
    parts = ranking.score_parts(
        CATALOGUE[0],
        models.SoftPreferences(colours=("beige",), styles=("modern",)),
        None,
    )
    assert [(p.component, p.value) for p in parts] == [
        ("colours", Decimal("1")),
        ("styles", Decimal("1")),
    ]
    assert ranking.combine(parts) == Decimal("1")


def test_closeness_is_linear_and_clamped() -> None:
    assert ranking._closeness(Decimal("220"), Decimal("220")) == Decimal("1")
    assert ranking._closeness(Decimal("165"), Decimal("220")) == Decimal("0.75")
    assert ranking._closeness(Decimal("440"), Decimal("220")) == Decimal("0")
    assert ranking._closeness(Decimal("900"), Decimal("220")) == Decimal("0")
    assert ranking._closeness(None, Decimal("220")) is None


def test_weighted_mean_is_recomputable_by_hand() -> None:
    soft = models.SoftPreferences(
        materials=("beech_wood", "mdf"),  # one of two present -> 0.5, weight 2
        preferred_width_cm=Decimal("200"),  # 220 vs 200 -> 0.9, weight 1
        target_price=Decimal("20000"),  # 10000 vs 20000 -> 0.5, weight 1.5
    )
    parts = ranking.score_parts(CATALOGUE[0], soft, None)
    assert {(p.component, p.value) for p in parts} == {
        ("materials", Decimal("0.5")),
        ("width", Decimal("0.9")),
        ("price", Decimal("0.5")),
    }
    expected = (
        Decimal("2") * Decimal("0.5") + Decimal("0.9") + Decimal("1.5") * Decimal("0.5")
    ) / Decimal("4.5")
    assert ranking.combine(parts) == expected.quantize(Decimal("0.0001"))


def test_query_overlap_matches_bilingual_terms_and_normalized_text() -> None:
    query = models.query_text("كنبة بيج مودرن")
    parts = ranking.score_parts(CATALOGUE[0], models.SoftPreferences(), query)
    assert parts[0].component == "query"
    assert parts[0].value == Decimal(
        "1"
    )  # كنبه (name), بيج (colour label), مودرن (name)
    other = ranking.score_parts(CATALOGUE[3], models.SoftPreferences(), query)
    assert other[0].value < Decimal("1")


def test_room_preference_only_matches_confirmed_room_attributes() -> None:
    soft = models.SoftPreferences(room_type="living room")
    assert ranking.score_parts(CATALOGUE[0], soft, None)[0].value == Decimal("1")
    assert ranking.score_parts(CATALOGUE[1], soft, None)[0].value == Decimal("0")


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------


def test_master_plan_query_returns_the_fitting_sofa_first_with_reasons() -> None:
    results = service.search_products(
        CATALOGUE,
        spec(
            category="sofa",
            price=models.PriceRange(maximum=Decimal("30000")),
            width=models.DimensionRange(maximum_cm=Decimal("220")),
            preferred_colours=("beige",),
            styles=("modern",),
            room_type="living room",
            query="modern beige sofa",
        ),
    )
    # Only the first sofa fits: the second is over budget, the third has no
    # stock, the bed is the wrong category, and the discounted sofa has no
    # known width so it cannot be proven to fit.
    assert results.match_count == 1
    assert results.items[0].product_id == CATALOGUE[0].id
    assert results.items[0].score == Decimal("1")
    assert {p.component for p in results.items[0].parts} == {
        "colours",
        "styles",
        "room_type",
        "query",
    }
    assert all(c.satisfied for c in results.items[0].checks)
    assert dict(results.rejections) == {
        "category": 1,
        "price": 1,
        "in_stock": 1,
        "width": 1,
    }
    assert results.candidate_count == 5
    assert results.has_more is False
    assert results.schema_version == 1


def test_hard_filters_exclude_before_any_scoring_and_report_rejections() -> None:
    results = service.search_products(CATALOGUE, spec(colours=("grey",), query="كنبة"))
    assert results.match_count == 0
    assert results.items == ()
    assert dict(results.rejections)["colours"] == 5
    assert dict(results.rejections)["in_stock"] == 1


def test_order_is_total_and_stable_with_price_and_id_tiebreaks() -> None:
    twins = (
        product("a0000000", price=12000, colours=(("بيج — beige", 1),)),
        product("b0000000", price=11000, colours=(("بيج — beige", 1),)),
        product("c0000000", price=11000, colours=(("بيج — beige", 1),)),
    )
    results = service.search_products(
        reversed(twins), spec(preferred_colours=("beige",))
    )
    assert [str(i.product_id)[:8] for i in results.items] == [
        "b0000000",
        "c0000000",
        "a0000000",
    ]
    again = service.search_products(twins, spec(preferred_colours=("beige",)))
    assert again == results


def test_paging_and_has_more_are_deterministic() -> None:
    results = service.search_products(CATALOGUE, spec(category="sofas", limit=1))
    assert len(results.items) == 1
    assert results.has_more is True
    assert results.match_count == 3  # the out-of-stock sofa is excluded
    assert results.items[0].effective_price == Decimal("7000")  # cheapest at score 0


def test_duplicate_or_excessive_candidates_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError):
        service.search_products((CATALOGUE[0], CATALOGUE[0]), spec(category="sofas"))
    monkeypatch.setattr(service, "MAX_CANDIDATES", 2)
    with pytest.raises(ValueError):
        service.search_products(CATALOGUE, spec(category="sofas"))


def test_results_expose_no_free_text_and_are_frozen() -> None:
    results = service.search_products(CATALOGUE, spec(category="sofas", query="كنبة"))
    dumped = results.model_dump_json()
    for private in ("كنبة مودرن", "Modern sofa", "Artisan"):
        assert private not in dumped
    with pytest.raises(ValidationError):
        results.limit = 1  # type: ignore[misc]


def test_search_package_is_pure() -> None:
    import inspect

    for module in (filters, ranking, service):
        source = inspect.getsource(module)
        for forbidden in ("httpx", "anthropic", "openai", "supabase", "os.environ"):
            assert forbidden not in source, (module.__name__, forbidden)
