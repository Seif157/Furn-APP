"""Deterministic tests for the Phase 4B catalogue normalization layer."""

import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from app.catalog import normalization as norm
from app.catalog.upstream_models import UpstreamProduct
from tests.test_catalog import product_payload

PRODUCT_ADAPTER = TypeAdapter(UpstreamProduct)


def upstream(**overrides: Any) -> UpstreamProduct:
    payload = product_payload()
    payload.update(overrides)
    return PRODUCT_ADAPTER.validate_json(json.dumps(payload), strict=True)


def audit_product() -> UpstreamProduct:
    """A product shaped like the four real rows the Phase 4A audit described."""

    payload = product_payload(name="كنبة ركنة مودرن ٣ مقاعد")
    payload["description"] = "Modern L-shaped sofa."
    payload["weight"] = None
    payload["materials"] = ["خشب زان", "قماش"]
    payload["category"]["name"] = "Sofas — كنب"
    payload["colors"] = [
        {
            "id": "51000000-0000-4000-8000-000000000000",
            "color_value": "بيج — beige",
            "stock_quantity": 2,
            "display_order": 1,
        },
        {
            "id": "52000000-0000-4000-8000-000000000000",
            "color_value": "رمادي — grey",
            "stock_quantity": 1,
            "display_order": 0,
        },
    ]
    payload["enrichment_assignments"] = []
    return PRODUCT_ADAPTER.validate_json(json.dumps(payload), strict=True)


# --------------------------------------------------------------------------
# Text normalization
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  Modern   BEIGE Sofa ", "modern beige sofa"),
        ("أَسِرَّة", "اسره"),  # diacritics stripped, alef and teh marbuta folded
        ("إبراهيم آدم", "ابراهيم ادم"),
        ("مصطفى", "مصطفي"),  # alef maqsura -> yeh
        ("٢٢٠ سم", "220 سم"),  # Arabic-Indic digits
        ("۲۲۰", "220"),  # Extended (Persian) digits
        ("٣٫٥", "3.5"),  # Arabic decimal separator
        ("ـمـمـ", "مم"),  # tatweel removed
        ("ﬁne", "fine"),  # NFKC compatibility fold
    ],
)
def test_normalize_text_folds_scripts_digits_and_whitespace(
    text: str, expected: str
) -> None:
    assert norm.normalize_text(text) == expected


def test_normalize_text_is_idempotent_on_audit_vocabulary() -> None:
    for surface in (
        "Beds — أسرّة",
        "أبيض — white",
        "خشب زان",
        "mdf",
        "Wardrobes — دواليب",
    ):
        once = norm.normalize_text(surface)
        assert norm.normalize_text(once) == once


# --------------------------------------------------------------------------
# Bilingual labels
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "arabic", "english"),
    [
        ("Beds — أسرّة", "أسرّة", "Beds"),
        ("أبيض — white", "أبيض", "white"),
        ("بني غامق — dark brown", "بني غامق", "dark brown"),
        ("Chairs – كراسي", "كراسي", "Chairs"),  # en dash
        ("Dining - سفرة", "سفرة", "Dining"),  # spaced hyphen
        ("Sofas | كنب", "كنب", "Sofas"),
        ("Wardrobes", None, "Wardrobes"),
        ("دواليب", "دواليب", None),
        ("dark-brown", None, "dark-brown"),  # unspaced hyphen is not a separator
        ("2024", None, "2024"),  # no script: kept as english fallback
    ],
)
def test_split_bilingual_label_uses_script_not_position(
    label: str, arabic: str | None, english: str | None
) -> None:
    assert norm.split_bilingual_label(label) == (arabic, english)


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("220 cm", "220.00"),
        ("220cm", "220.00"),
        ("2.2 m", "220.00"),
        ("2,2 m", "220.00"),
        ("2200 mm", "220.00"),
        ("٢٢٠ سم", "220.00"),
        ("عرض ٢٫٢ متر", "220.00"),
        ("86.6 in", "219.96"),
        ('86.6"', "219.96"),
        ("width 90 cm height 180 cm", "90.00"),  # first quantity wins
        ("no size given", None),
        ("٣ مقاعد", None),  # a bare Arabic meem is not the metre unit
        ("0 cm", None),
        ("cm 220", None),
        ("220 cmx", None),  # unit must end the token
    ],
)
def test_parse_length_cm(text: str, expected: str | None) -> None:
    result = norm.parse_length_cm(text)
    assert result == (Decimal(expected) if expected is not None else None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12.5 kg", "12.50"),
        ("12500 g", "12.50"),
        ("٢٠ كجم", "20.00"),
        ("27 lb", "12.25"),
        ("heavy", None),
    ],
)
def test_parse_weight_kg(text: str, expected: str | None) -> None:
    result = norm.parse_weight_kg(text)
    assert result == (Decimal(expected) if expected is not None else None)


# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------


def test_every_audit_token_resolves_to_a_verified_term() -> None:
    audit_categories = {
        "Beds — أسرّة": "beds",
        "Dining — سفرة": "dining",
        "Sofas — كنب": "sofas",
        "Wardrobes — دواليب": "wardrobes",
        "Chairs — كراسي": "chairs",
    }
    audit_colours = {
        "أبيض — white": "white",
        "بني — brown": "brown",
        "بني غامق — dark brown": "dark_brown",
        "بيج — beige": "beige",
        "رمادي — grey": "grey",
        "طبيعي — natural": "natural",
        "كحلي — navy": "navy",
        "وينجيه — wenge": "wenge",
    }
    audit_materials = {
        "خشب زان": "beech_wood",
        "mdf": "mdf",
        "خشب": "wood",
        "قطن": "cotton",
        "قماش": "fabric",
    }
    for vocabulary, expected in (
        (norm.CATEGORIES, audit_categories),
        (norm.COLOURS, audit_colours),
        (norm.MATERIALS, audit_materials),
    ):
        for surface, slug in expected.items():
            term = vocabulary.lookup(surface)
            assert term is not None, surface
            assert term.slug == slug, surface
            assert term.verified, surface


def test_lookup_resolves_either_half_and_synonyms_and_rejects_conflicts() -> None:
    assert norm.COLOURS.lookup("GRAY").slug == "grey"
    assert norm.COLOURS.lookup("رمادى").slug == "grey"  # alef maqsura variant
    assert norm.CATEGORIES.lookup("couch").slug == "sofas"
    assert norm.CATEGORIES.lookup("كنبة").slug == "sofas"
    assert norm.MATERIALS.lookup("Solid Wood").slug == "wood"
    assert norm.COLOURS.lookup("turquoise") is None
    # A label whose halves resolve to different terms is ambiguous, not guessed.
    assert norm.COLOURS.lookup("أبيض — brown") is None


def test_vocabularies_have_unique_slugs_and_no_cross_term_synonyms() -> None:
    for vocabulary in (norm.CATEGORIES, norm.COLOURS, norm.MATERIALS):
        slugs = [term.slug for term in vocabulary.terms]
        assert len(slugs) == len(set(slugs)), vocabulary.name
        for term in vocabulary.terms:
            assert term.english and term.arabic, term.slug
            for surface in (term.english, term.arabic, *term.synonyms):
                assert vocabulary.lookup(surface) is term, (vocabulary.name, surface)
    with pytest.raises(ValueError):
        norm.Vocabulary(
            "broken",
            (
                norm.VocabularyTerm("a", "same", "أ"),
                norm.VocabularyTerm("b", "same", "ب"),
            ),
        )


# --------------------------------------------------------------------------
# Product normalization
# --------------------------------------------------------------------------


def test_normalize_product_keeps_originals_and_adds_canonical_forms() -> None:
    product = normalized = norm.normalize_product(audit_product())
    assert normalized.name.original == "كنبة ركنة مودرن ٣ مقاعد"
    assert normalized.name.normalized == "كنبه ركنه مودرن 3 مقاعد"
    assert normalized.name.has_arabic and not normalized.name.has_latin
    assert normalized.description is not None
    assert normalized.description.normalized == "modern l-shaped sofa."
    assert normalized.category.original == "Sofas — كنب"
    assert normalized.category.slug == "sofas"
    assert normalized.category.label_ar == "كنب"
    assert normalized.category.verified
    assert [colour.slug for colour in normalized.colours] == ["grey", "beige"]
    assert [colour.stock_quantity for colour in normalized.colours] == [1, 2]
    assert [material.slug for material in normalized.materials] == [
        "beech_wood",
        "fabric",
    ]
    assert [material.original for material in normalized.materials] == [
        "خشب زان",
        "قماش",
    ]
    assert normalized.width_cm == Decimal("80.5")
    assert normalized.weight_kg is None
    assert normalized.effective_price == Decimal("749.5")
    assert normalized.attributes == ()
    assert normalized.unmapped_terms == ()
    assert normalized.schema_version == 1
    assert product is normalized


def test_search_terms_are_sorted_unique_and_bilingual() -> None:
    normalized = norm.normalize_product(audit_product())
    assert normalized.search_terms == tuple(sorted(set(normalized.search_terms)))
    for expected in (
        "sofas",
        "sofas — كنب",
        "كنب",
        "beige",
        "بيج",
        "grey",
        "رمادي",
        "beech_wood",
        "خشب زان",
        "fabric",
        "قماش",
    ):
        assert expected in normalized.search_terms, expected


def test_unmapped_terms_are_surfaced_not_guessed() -> None:
    normalized = norm.normalize_product(
        upstream(materials=["oak", "linen", "recycled ocean plastic"])
    )
    assert [m.slug for m in normalized.materials] == ["oak", "linen", None]
    assert normalized.unmapped_terms == ("recycled ocean plastic",)
    assert normalized.category.slug == "chairs"
    # display_order 0 first, then the two order-2 colours by UUID.
    assert [c.slug for c in normalized.colours] == ["natural", "oak", "walnut"]


def test_only_confirmed_enrichment_attributes_are_used_and_sorted() -> None:
    normalized = norm.normalize_product(upstream())
    assert [(a.kind, a.value_normalized) for a in normalized.attributes] == [
        ("color_family", "warm"),
        ("style", "classic"),
        ("style", "contemporary"),
    ]
    assert not any("private" in term for term in normalized.search_terms)
    assert "style:classic" in normalized.search_terms


def test_effective_price_ignores_discounts_that_are_not_below_price() -> None:
    assert norm.normalize_product(upstream(discount_price=None)).effective_price == (
        Decimal("799.99")
    )
    assert norm.normalize_product(upstream(discount_price=799.99)).effective_price == (
        Decimal("799.99")
    )
    assert norm.normalize_product(upstream(discount_price=100)).effective_price == (
        Decimal("100")
    )


def test_normalization_is_deterministic_and_frozen() -> None:
    first = norm.normalize_product(audit_product())
    second = norm.normalize_product(audit_product())
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    with pytest.raises(ValidationError):
        first.name = first.description  # type: ignore[misc]


def test_module_is_pure_and_has_no_network_or_provider_imports() -> None:
    import inspect

    source = inspect.getsource(norm)
    for forbidden in (
        "httpx",
        "requests",
        "anthropic",
        "openai",
        "supabase",
        "os.environ",
    ):
        assert forbidden not in source, forbidden
