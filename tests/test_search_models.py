"""Deterministic tests for the Phase 4C search specification models."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.search import models as search


def test_master_plan_example_builds_into_a_valid_specification() -> None:
    # "I need a modern beige sofa around 220 cm for a small living room under
    # 30,000 EGP."  -> category sofa, max price 30000, max width 220, in stock,
    # style modern, colour beige.
    build = search.build_specification(
        category="sofa",
        price=search.PriceRange(maximum=Decimal("30000")),
        width=search.DimensionRange(maximum_cm=Decimal("220")),
        preferred_colours=("beige",),
        styles=("Modern",),
        room_type="Living Room",
        preferred_width_cm=Decimal("220"),
        query="I need a modern beige sofa around 220 cm under 30,000 EGP",
    )
    spec = build.specification
    assert build.unresolved == ()
    assert spec.hard.category == "sofas"
    assert spec.hard.price == search.PriceRange(maximum=Decimal("30000"))
    assert spec.hard.width == search.DimensionRange(maximum_cm=Decimal("220"))
    assert spec.hard.in_stock_only is True
    assert spec.soft.colours == ("beige",)
    assert spec.soft.styles == ("modern",)
    assert spec.soft.room_type == "living room"
    assert spec.query is not None and spec.query.language == "en"
    assert spec.limit == 20
    assert spec.schema_version == 1


def test_arabic_and_bilingual_surfaces_resolve_to_the_same_slugs() -> None:
    arabic = search.build_specification(
        category="كنب", colours=("بيج",), materials=("خشب زان",), query="عايز كنبة بيج"
    )
    english = search.build_specification(
        category="Sofas — كنب", colours=("Beige",), materials=("beech",)
    )
    assert arabic.specification.hard == english.specification.hard
    assert arabic.specification.hard.materials == ("beech_wood",)
    assert arabic.specification.query is not None
    assert arabic.specification.query.language == "ar"
    assert arabic.specification.query.normalized == "عايز كنبه بيج"
    assert search.detect_language("modern كنبة") == "mixed"


def test_unresolved_surfaces_are_reported_not_guessed() -> None:
    build = search.build_specification(
        category="hammock",
        colours=("beige", "turquoise", "gray", "GREY"),
        preferred_materials=("recycled ocean plastic",),
    )
    assert build.specification.hard.category is None
    assert build.specification.hard.colours == ("beige", "grey")  # de-duplicated
    assert build.unresolved == (
        search.UnresolvedTerm(field="category", surface="hammock"),
        search.UnresolvedTerm(field="colours", surface="turquoise"),
        search.UnresolvedTerm(
            field="preferred_materials", surface="recycled ocean plastic"
        ),
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"category": "hammock"},
        {"colours": ("turquoise",)},
        {"materials": ("plastic",)},
        {"colours": ("beige", "beige")},
        {"colours": tuple(f"c{i}" for i in range(11))},
    ],
)
def test_hard_constraints_reject_unknown_or_duplicate_slugs(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        search.HardConstraints(**kwargs)


@pytest.mark.parametrize(
    ("model", "kwargs"),
    [
        (search.PriceRange, {}),
        (search.PriceRange, {"minimum": Decimal("-1")}),
        (search.PriceRange, {"minimum": Decimal("10"), "maximum": Decimal("5")}),
        (search.PriceRange, {"maximum": Decimal("1e12")}),
        (search.PriceRange, {"maximum": Decimal("NaN")}),
        (search.DimensionRange, {}),
        (search.DimensionRange, {"minimum_cm": Decimal("0")}),
        (
            search.DimensionRange,
            {"minimum_cm": Decimal("300"), "maximum_cm": Decimal("200")},
        ),
        (search.DimensionRange, {"maximum_cm": Decimal("1e9")}),
    ],
)
def test_ranges_reject_empty_negative_inverted_or_absurd_bounds(
    model: type, kwargs: dict
) -> None:
    with pytest.raises(ValidationError):
        model(**kwargs)


def test_ranges_accept_single_or_ordered_bounds() -> None:
    assert search.PriceRange(minimum=Decimal("0")).maximum is None
    assert search.PriceRange(minimum=Decimal("5"), maximum=Decimal("5")).minimum == 5
    assert search.DimensionRange(maximum_cm=Decimal("0.5")).minimum_cm is None


def test_soft_preferences_require_normalized_text_and_positive_targets() -> None:
    with pytest.raises(ValidationError):
        search.SoftPreferences(styles=("Modern",))  # not normalized
    with pytest.raises(ValidationError):
        search.SoftPreferences(styles=("modern", "modern"))
    with pytest.raises(ValidationError):
        search.SoftPreferences(room_type="")
    with pytest.raises(ValidationError):
        search.SoftPreferences(preferred_width_cm=Decimal("-1"))
    with pytest.raises(ValidationError):
        search.SoftPreferences(target_price=Decimal("0"))
    assert search.SoftPreferences(styles=("modern", "مودرن")).styles == (
        "modern",
        "مودرن",
    )


def test_specification_needs_some_signal_and_bounded_limit() -> None:
    with pytest.raises(ValidationError):
        search.SearchSpecification()
    with pytest.raises(ValidationError):
        search.SearchSpecification(hard=search.HardConstraints(in_stock_only=False))
    with pytest.raises(ValidationError):
        search.SearchSpecification(
            hard=search.HardConstraints(category="beds"), limit=0
        )
    with pytest.raises(ValidationError):
        search.SearchSpecification(
            hard=search.HardConstraints(category="beds"), limit=51
        )
    assert search.SearchSpecification(query=search.query_text("سرير")).limit == 20
    assert search.SearchSpecification(
        soft=search.SoftPreferences(styles=("modern",))
    ).hard.in_stock_only


def test_query_text_is_consistent_bounded_and_language_tagged() -> None:
    query = search.query_text("Modern كنبة ٣ مقاعد")
    assert query.language == "mixed"
    assert query.normalized == "modern كنبه 3 مقاعد"
    with pytest.raises(ValidationError):
        search.QueryText(original="x", normalized="y", language="en")
    with pytest.raises(ValidationError):
        search.QueryText(original="سرير", normalized="سرير", language="en")
    with pytest.raises(ValidationError):
        search.query_text("   ")
    with pytest.raises(ValidationError):
        search.query_text("x" * 501)


def test_specification_is_frozen_strict_and_round_trips_json() -> None:
    spec = search.build_specification(
        category="beds",
        price=search.PriceRange(minimum=Decimal("1000"), maximum=Decimal("2000.50")),
        materials=("mdf", "قماش"),
        query="سرير",
    ).specification
    with pytest.raises(ValidationError):
        spec.limit = 5  # type: ignore[misc]
    with pytest.raises(ValidationError):
        search.HardConstraints(category="beds", unknown="x")  # type: ignore[call-arg]
    restored = search.SearchSpecification.model_validate_json(spec.model_dump_json())
    assert restored == spec
    assert restored.hard.price is not None
    assert restored.hard.price.maximum == Decimal("2000.50")


def test_package_is_pure() -> None:
    import inspect

    source = inspect.getsource(search)
    for forbidden in ("httpx", "anthropic", "openai", "supabase", "os.environ"):
        assert forbidden not in source, forbidden
