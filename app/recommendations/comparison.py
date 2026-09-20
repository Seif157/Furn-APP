"""Side-by-side comparison of real products (Phase 6D).

Deterministic, like the rest of Phase 6. No provider is called, so nothing here
can invent a price, a size, or a verdict.

A comparison states facts and marks where products differ; it does not declare
a winner. "Cheapest" and "smallest footprint" are facts. "Better" depends on
what the customer needs, which this endpoint is not told, so it never says it.
A row is highlighted only when its values actually differ, because marking one
of three identical prices as "lowest" would be noise dressed up as insight.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from uuid import UUID

from app.catalog.models import ProductResponse, StrictResponseModel
from app.catalog.normalization import COLOURS, MATERIALS, NormalizedProduct, Term
from app.recommendations.explanations import format_money
from app.recommendations.models import ReasonResponse
from app.search.localization import response_language, term_label
from app.search.models import Language

MIN_COMPARED = 2
MAX_COMPARED = 4

LABELS: dict[str, dict[str, str]] = {
    "price": {"en": "Price", "ar": "السعر"},
    "discount": {"en": "Discount", "ar": "الخصم"},
    "width_cm": {"en": "Width", "ar": "العرض"},
    "depth_cm": {"en": "Depth", "ar": "العمق"},
    "height_cm": {"en": "Height", "ar": "الارتفاع"},
    "footprint": {"en": "Floor space", "ar": "المساحة على الأرض"},
    "weight_kg": {"en": "Weight", "ar": "الوزن"},
    "materials": {"en": "Materials", "ar": "الخامات"},
    "colours": {"en": "Colours in stock", "ar": "الألوان المتاحة"},
    "stock": {"en": "Units in stock", "ar": "الكمية المتاحة"},
    "seller": {"en": "Seller", "ar": "البائع"},
}
UNKNOWN = {"en": "Not listed", "ar": "غير مذكور"}
NONE = {"en": "None", "ar": "لا يوجد"}


class ComparisonValue(StrictResponseModel):
    product_id: UUID
    text: str
    """Display copy in the customer's language."""
    value: Decimal | None
    """The number behind ``text`` where there is one, for sorting or charts."""


class ComparisonRow(StrictResponseModel):
    code: str
    label: str
    values: tuple[ComparisonValue, ...]
    highlight: tuple[UUID, ...]
    """Products holding the row's notable value: lowest price, largest discount,
    smallest floor space, most units. Empty when every value is the same or
    the row has no notable direction."""
    highlight_rule: str | None


class ComparisonResponse(StrictResponseModel):
    language: str
    products: tuple[ProductResponse, ...]
    rows: tuple[ComparisonRow, ...]
    summary: tuple[ReasonResponse, ...]


def _number(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        return f"{int(normalized):,}"
    return f"{normalized:,f}"


def _term_text(term: Term, vocabulary, language: Language) -> str:
    return term_label(vocabulary, term.slug, language) if term.slug else term.original


def _in_stock_colours(product: NormalizedProduct):
    return tuple(c for c in product.colours if c.stock_quantity > 0)


def _stock(product: NormalizedProduct) -> Decimal:
    return Decimal(sum(c.stock_quantity for c in _in_stock_colours(product)))


def _footprint(product: NormalizedProduct) -> Decimal | None:
    if product.width_cm is None or product.depth_cm is None:
        return None
    return product.width_cm * product.depth_cm


def _discount(product: NormalizedProduct) -> Decimal:
    return product.price - product.effective_price


def _extreme(
    products: Sequence[NormalizedProduct],
    measure: Callable[[NormalizedProduct], Decimal | None],
    *,
    lowest: bool,
) -> tuple[UUID, ...]:
    """Ids holding the lowest or highest value, only if every value is known
    and they are not all equal."""

    values = [measure(p) for p in products]
    if any(v is None for v in values) or len(set(values)) < 2:
        return ()
    target = min(values) if lowest else max(values)
    return tuple(p.id for p, v in zip(products, values, strict=True) if v == target)


def _numeric_row(
    code: str,
    products: Sequence[NormalizedProduct],
    measure: Callable[[NormalizedProduct], Decimal | None],
    render: Callable[[Decimal], str],
    language: Language,
    *,
    rule: str | None = None,
) -> ComparisonRow:
    lang = response_language(language)
    values = tuple(
        ComparisonValue(
            product_id=p.id,
            text=render(value) if (value := measure(p)) is not None else UNKNOWN[lang],
            value=value,
        )
        for p in products
    )
    highlight: tuple[UUID, ...] = ()
    if rule in ("lowest", "smallest"):
        highlight = _extreme(products, measure, lowest=True)
    elif rule in ("largest", "most"):
        highlight = _extreme(products, measure, lowest=False)
    return ComparisonRow(
        code=code,
        label=LABELS[code][lang],
        values=values,
        highlight=highlight,
        highlight_rule=rule if highlight else None,
    )


def _text_row(
    code: str,
    products: Sequence[NormalizedProduct],
    render: Callable[[NormalizedProduct], str],
    language: Language,
) -> ComparisonRow:
    return ComparisonRow(
        code=code,
        label=LABELS[code][response_language(language)],
        values=tuple(
            ComparisonValue(product_id=p.id, text=render(p), value=None)
            for p in products
        ),
        highlight=(),
        highlight_rule=None,
    )


def build_comparison(
    products: Sequence[NormalizedProduct],
    responses: Sequence[ProductResponse],
    sellers: dict[UUID, str],
    language: Language,
) -> ComparisonResponse:
    """Compare products in the order the customer listed them."""

    lang = response_language(language)
    cm = "سم" if lang == "ar" else "cm"
    kg = "كجم" if lang == "ar" else "kg"
    sq = "سم²" if lang == "ar" else "cm²"

    def money(value: Decimal) -> str:
        return format_money(value, language)

    def joined(terms: Sequence[str]) -> str:
        return "، ".join(terms) if lang == "ar" else ", ".join(terms)

    rows = (
        _numeric_row(
            "price",
            products,
            lambda p: p.effective_price,
            money,
            language,
            rule="lowest",
        ),
        _numeric_row(
            "discount",
            products,
            _discount,
            lambda d: money(d) if d > 0 else NONE[lang],
            language,
            rule="largest",
        ),
        _numeric_row(
            "width_cm",
            products,
            lambda p: p.width_cm,
            lambda v: f"{_number(v)} {cm}",
            language,
        ),
        _numeric_row(
            "depth_cm",
            products,
            lambda p: p.depth_cm,
            lambda v: f"{_number(v)} {cm}",
            language,
        ),
        _numeric_row(
            "height_cm",
            products,
            lambda p: p.height_cm,
            lambda v: f"{_number(v)} {cm}",
            language,
        ),
        _numeric_row(
            "footprint",
            products,
            _footprint,
            lambda v: f"{_number(v)} {sq}",
            language,
            rule="smallest",
        ),
        _numeric_row(
            "weight_kg",
            products,
            lambda p: p.weight_kg,
            lambda v: f"{_number(v)} {kg}",
            language,
        ),
        _text_row(
            "materials",
            products,
            lambda p: (
                joined([_term_text(m, MATERIALS, language) for m in p.materials])
                or UNKNOWN[lang]
            ),
            language,
        ),
        _text_row(
            "colours",
            products,
            lambda p: (
                joined([_term_text(c, COLOURS, language) for c in _in_stock_colours(p)])
                or NONE[lang]
            ),
            language,
        ),
        _numeric_row(
            "stock", products, _stock, lambda v: _number(v), language, rule="most"
        ),
        _text_row("seller", products, lambda p: sellers[p.id], language),
    )

    return ComparisonResponse(
        language=lang,
        products=tuple(responses),
        rows=rows,
        summary=_summary(products, rows, language),
    )


def _summary(
    products: Sequence[NormalizedProduct],
    rows: Sequence[ComparisonRow],
    language: Language,
) -> tuple[ReasonResponse, ...]:
    """A few plain sentences restating highlighted rows."""

    lang = response_language(language)
    names = {p.id: p.name.original for p in products}
    by_code = {row.code: row for row in rows}
    sentences: list[ReasonResponse] = []

    price = by_code["price"]
    if price.highlight:
        cheapest = price.highlight[0]
        prices = [v.value for v in price.values if v.value is not None]
        gap = max(prices) - min(prices)
        text = (
            f"الأرخص: {names[cheapest]}، بفرق {format_money(gap, language)} عن الأغلى"
            if lang == "ar"
            else f"Cheapest: {names[cheapest]}, "
            f"{format_money(gap, language)} less than the most expensive"
        )
        sentences.append(ReasonResponse(code="cheapest", text=text))

    footprint = by_code["footprint"]
    if footprint.highlight:
        smallest = footprint.highlight[0]
        text = (
            f"الأصغر مساحة على الأرض: {names[smallest]}"
            if lang == "ar"
            else f"Takes the least floor space: {names[smallest]}"
        )
        sentences.append(ReasonResponse(code="smallest_footprint", text=text))

    stock = by_code["stock"]
    if stock.highlight:
        most = stock.highlight[0]
        text = (
            f"الأكثر توفرًا: {names[most]}"
            if lang == "ar"
            else f"Most units in stock: {names[most]}"
        )
        sentences.append(ReasonResponse(code="most_stock", text=text))

    return tuple(sentences)
