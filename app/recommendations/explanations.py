"""Grounded reasons, built from checks that already ran (Phase 6C).

Section 6.6 of the master plan draws the line: "This sofa fits your width limit
because its catalogue width is 218 cm" is a fact; "this sofa feels cosy" is
not. Everything produced here is the first kind. Each sentence restates a
number or a term the catalogue holds, next to the limit the customer stated.

No provider is involved. ``ConstraintCheck`` already carries the observed
product value, because Phase 4D recorded it precisely so a caller could explain
an outcome without re-deriving the rule. This module reads that back.

Only constraints the customer actually stated produce a reason. An
unconstrained check passes trivially, and saying "it is in your price range"
when no budget was given would be noise dressed up as insight.
"""

from __future__ import annotations

from decimal import Decimal

from app.catalog.normalization import (
    CATEGORIES,
    COLOURS,
    MATERIALS,
    NormalizedProduct,
)
from app.recommendations.models import ReasonResponse
from app.search.localization import response_language, term_label
from app.search.models import HardConstraints, Language, SoftPreferences
from app.search.ranking import SOFT_DIMENSIONS, dimension_strengths
from app.search.results import ConstraintCheck

CURRENCY = {"en": "EGP", "ar": "جنيه"}


def _number(value: Decimal) -> str:
    """Render a decimal without trailing zeros, with thousands separators."""

    quantized = value.normalize()
    if quantized == quantized.to_integral_value():
        return f"{int(quantized):,}"
    return f"{quantized:,f}"


def _money(value: Decimal, language: Language) -> str:
    return f"{_number(value)} {CURRENCY[response_language(language)]}"


def format_money(value: Decimal, language: Language) -> str:
    """Public form of the money formatting every grounded sentence uses."""

    return _money(value, language)


def _observed_decimal(check: ConstraintCheck) -> Decimal | None:
    if check.observed is None:
        return None
    try:
        return Decimal(check.observed)
    except ArithmeticError:
        return None


def _dimension_reason(
    check: ConstraintCheck, maximum: Decimal | None, language: Language
) -> ReasonResponse | None:
    observed = _observed_decimal(check)
    if observed is None or maximum is None:
        return None
    axis = {
        "width": {"en": "wide", "ar": "عرض"},
        "height": {"en": "tall", "ar": "ارتفاع"},
        "depth": {"en": "deep", "ar": "عمق"},
    }[check.name]
    if response_language(language) == "ar":
        text = f"{axis['ar']} {_number(observed)} سم، في حدود {_number(maximum)} سم"
    else:
        text = (
            f"{_number(observed)} cm {axis['en']}, within your "
            f"{_number(maximum)} cm limit"
        )
    return ReasonResponse(code=check.name, text=text)


def match_reasons(
    checks: tuple[ConstraintCheck, ...],
    hard: HardConstraints,
    language: Language,
) -> tuple[ReasonResponse, ...]:
    """Say why this product satisfies what the customer asked for."""

    arabic = response_language(language) == "ar"
    by_name = {check.name: check for check in checks}
    reasons: list[ReasonResponse] = []

    if hard.category is not None:
        label = term_label(CATEGORIES, hard.category, language)
        reasons.append(
            ReasonResponse(
                code="category",
                text=f"{label}" if arabic else f"a match for {label.lower()}",
            )
        )

    if hard.colours:
        check = by_name.get("colours")
        available = set((check.observed or "").split(",")) if check else set()
        wanted = [slug for slug in hard.colours if slug in available]
        if wanted:
            labels = ", ".join(term_label(COLOURS, slug, language) for slug in wanted)
            reasons.append(
                ReasonResponse(
                    code="colours",
                    text=f"متوفر باللون {labels}"
                    if arabic
                    else f"in stock in {labels}",
                )
            )

    if hard.materials:
        labels = ", ".join(
            term_label(MATERIALS, slug, language) for slug in hard.materials
        )
        reasons.append(
            ReasonResponse(
                code="materials",
                text=f"مصنوع من {labels}" if arabic else f"made of {labels}",
            )
        )

    price_check = by_name.get("price")
    if hard.price is not None and price_check is not None:
        observed = _observed_decimal(price_check)
        if observed is not None:
            if hard.price.maximum is not None:
                text = (
                    f"{_money(observed, language)}، في حدود "
                    f"{_money(hard.price.maximum, language)}"
                    if arabic
                    else (
                        f"{_money(observed, language)}, within your "
                        f"{_money(hard.price.maximum, language)} budget"
                    )
                )
            else:
                text = _money(observed, language)
            reasons.append(ReasonResponse(code="price", text=text))

    for name, bounds in (
        ("width", hard.width),
        ("height", hard.height),
        ("depth", hard.depth),
    ):
        check = by_name.get(name)
        if bounds is not None and check is not None:
            reason = _dimension_reason(check, bounds.maximum_cm, language)
            if reason is not None:
                reasons.append(reason)

    if hard.in_stock_only:
        reasons.append(
            ReasonResponse(code="in_stock", text="متوفر" if arabic else "in stock")
        )

    return tuple(reasons)


# How a guess is worded, against how a seller-stated fact is worded. The
# difference is deliberate and visible: a customer must be able to tell which
# statements the marketplace stands behind.
_INFERRED_PHRASING = {
    "styles": {"en": "looks {label}", "ar": "شكله {label}"},
    "feels": {"en": "feels {label}", "ar": "إحساسه {label}"},
    "room_type": {"en": "suits a {label}", "ar": "مناسب لـ{label}"},
}
_CONFIRMED_PHRASING = {
    "styles": {"en": "{label}", "ar": "{label}"},
    "feels": {"en": "{label}", "ar": "{label}"},
    "room_type": {"en": "for a {label}", "ar": "لـ{label}"},
}
_OUR_GUESS = {"en": " (our guess)", "ar": " (تقديرنا)"}


def preference_reasons(
    product: NormalizedProduct,
    soft: SoftPreferences,
    language: Language,
) -> tuple[ReasonResponse, ...]:
    """Say which style, room, or feel the product answered, and on whose word.

    These are the only reasons that are not catalogue facts, so each one is
    marked. A guess is never stated as a fact, and a match that scored nothing
    produces no sentence at all: silence is the honest report for a product
    that simply does not carry the tag.
    """

    arabic = response_language(language) == "ar"
    key = "ar" if arabic else "en"
    wanted = {
        "styles": soft.styles,
        "feels": soft.feels,
        "room_type": (soft.room_type,) if soft.room_type is not None else (),
    }
    reasons: list[ReasonResponse] = []
    for component, slugs in wanted.items():
        if not slugs:
            continue
        confirmed_kinds, tag_kind, vocabulary = SOFT_DIMENSIONS[component]
        strengths = dimension_strengths(
            product,
            confirmed_kinds=confirmed_kinds,
            tag_kind=tag_kind,
            vocabulary=vocabulary,
        )
        for slug in slugs:
            strength = strengths.get(slug)
            if strength is None:
                continue
            label = term_label(vocabulary, slug, language)
            stated = strength >= 1
            phrasing = _CONFIRMED_PHRASING if stated else _INFERRED_PHRASING
            text = phrasing[component][key].format(label=label)
            if not stated:
                text += _OUR_GUESS[key]
            reasons.append(
                ReasonResponse(
                    code=component,
                    text=text,
                    basis="catalogue" if stated else "inferred",
                )
            )
    return tuple(reasons)


def shortfall_reasons(
    checks: tuple[ConstraintCheck, ...],
    hard: HardConstraints,
    language: Language,
) -> tuple[ReasonResponse, ...]:
    """Say what this product fails, and by how much where that is a number."""

    arabic = response_language(language) == "ar"
    reasons: list[ReasonResponse] = []

    for check in checks:
        if check.satisfied:
            continue
        observed = _observed_decimal(check)

        if check.name == "price" and hard.price is not None:
            maximum = hard.price.maximum
            if observed is not None and maximum is not None and observed > maximum:
                over = observed - maximum
                reasons.append(
                    ReasonResponse(
                        code="price",
                        text=(
                            f"أغلى بـ {_money(over, language)} من ميزانيتك"
                            if arabic
                            else f"{_money(over, language)} over your budget"
                        ),
                    )
                )
                continue

        if check.name in ("width", "height", "depth"):
            bounds = getattr(hard, check.name)
            maximum = bounds.maximum_cm if bounds is not None else None
            if observed is None:
                reasons.append(
                    ReasonResponse(
                        code=check.name,
                        text=(
                            "المقاس غير مسجل" if arabic else "its size is not recorded"
                        ),
                    )
                )
                continue
            if maximum is not None and observed > maximum:
                over = observed - maximum
                reasons.append(
                    ReasonResponse(
                        code=check.name,
                        text=(
                            f"أكبر بـ {_number(over)} سم من المقاس المطلوب"
                            if arabic
                            else f"{_number(over)} cm over your size limit"
                        ),
                    )
                )
                continue

        if check.name == "category":
            reasons.append(
                ReasonResponse(
                    code="category",
                    text="نوع مختلف" if arabic else "a different category",
                )
            )
            continue
        if check.name == "colours":
            reasons.append(
                ReasonResponse(
                    code="colours",
                    text=(
                        "مش متوفر باللون المطلوب"
                        if arabic
                        else "not available in that colour"
                    ),
                )
            )
            continue
        if check.name == "materials":
            reasons.append(
                ReasonResponse(
                    code="materials",
                    text="خامة مختلفة" if arabic else "a different material",
                )
            )
            continue
        if check.name == "in_stock":
            reasons.append(
                ReasonResponse(
                    code="in_stock",
                    text="غير متوفر حاليًا" if arabic else "out of stock",
                )
            )
            continue

        reasons.append(
            ReasonResponse(
                code=check.name,
                text="مش مطابق" if arabic else "does not match",
            )
        )

    return tuple(reasons)
