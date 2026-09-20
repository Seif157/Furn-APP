"""Ask the one question worth asking, with answers the customer can tap.

Phase 7A. The parser already returns a question when a sentence is too vague to
search, but a question alone leaves the customer typing again, and it says
nothing about what this catalogue can actually offer. This module turns it into
a choice built from the products that were really found.

Two rules decide whether anything is asked at all, and both come from section
6.3 of the master plan: ask only when needed, and search immediately when the
sentence is detailed. So a question appears when the parser asked one, or when
the customer named no kind of furniture and the result is consequently
everything. A sentence with a category and a budget is answered, not
interrogated.

Every option is grounded. Categories offered are categories that have matching
products; price bands are computed from those products' real prices. Nothing
here invents a choice the catalogue cannot honour, and tapping one sends an
ordinary sentence back through the ordinary parser, so a tapped answer and a
typed answer travel the same path.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.catalog.normalization import CATEGORIES, NormalizedProduct
from app.recommendations.explanations import format_money
from app.search.localization import response_language, term_label
from app.search.models import Language, SearchSpecification

FollowUpField = Literal["category", "price"]

MIN_BROAD_MATCHES = 8
"""Below this, a categoryless search is a short list the customer can read."""

MIN_PRICE_SPREAD = Decimal("1.5")
"""Offer bands only when the dearest option costs at least half again as much
as the cheapest. Splitting a narrow range asks the customer to choose between
things that are, to them, the same price."""

MAX_OPTIONS = 5

QUESTIONS: dict[FollowUpField, dict[Literal["ar", "en"], str]] = {
    "category": {
        "en": "What are you looking for?",
        "ar": "بتدور على إيه؟",
    },
    "price": {
        "en": "What is your budget?",
        "ar": "ميزانيتك قد إيه؟",
    },
}

UNDER = {"en": "under {amount}", "ar": "أقل من {amount}"}
BETWEEN = {"en": "{low} to {high}", "ar": "من {low} لـ{high}"}
OVER = {"en": "over {amount}", "ar": "أكتر من {amount}"}


@dataclass(frozen=True, slots=True)
class FollowUpOption:
    """One tappable answer.

    ``send`` is an ordinary sentence in the customer's language. The app sends
    it as the next query with the previous message as history, so a tap is
    indistinguishable from typing and needs no new server state.
    """

    value: str
    label: str
    send: str


@dataclass(frozen=True, slots=True)
class FollowUp:
    field: FollowUpField
    question: str
    options: tuple[FollowUpOption, ...]


def _round_money(value: Decimal) -> Decimal:
    """Round to something a person would say: 14,873 becomes 15,000."""

    if value >= 10000:
        step = Decimal("1000")
    elif value >= 1000:
        step = Decimal("500")
    else:
        step = Decimal("100")
    return (value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step


def _category_options(
    products: tuple[NormalizedProduct, ...], language: Language
) -> tuple[FollowUpOption, ...]:
    counted: dict[str, int] = {}
    for product in products:
        slug = product.category.slug
        if slug is not None:
            counted[slug] = counted.get(slug, 0) + 1
    ranked = sorted(counted.items(), key=lambda item: (-item[1], item[0]))
    options = []
    for slug, _count in ranked[:MAX_OPTIONS]:
        label = term_label(CATEGORIES, slug, language)
        options.append(FollowUpOption(value=slug, label=label, send=label))
    return tuple(options)


def _price_options(
    products: tuple[NormalizedProduct, ...], language: Language
) -> tuple[FollowUpOption, ...]:
    prices = sorted(product.effective_price for product in products)
    if len(prices) < 3:
        return ()
    cheapest, dearest = prices[0], prices[-1]
    if cheapest <= 0 or dearest / cheapest < MIN_PRICE_SPREAD:
        return ()
    low = _round_money(prices[len(prices) // 3])
    high = _round_money(prices[2 * len(prices) // 3])
    if not cheapest < low < high < dearest:
        return ()

    key = response_language(language)
    return (
        FollowUpOption(
            value=f"max:{low}",
            label=UNDER[key].format(amount=format_money(low, language)),
            send=UNDER[key].format(amount=format_money(low, language)),
        ),
        FollowUpOption(
            value=f"{low}:{high}",
            label=BETWEEN[key].format(
                low=format_money(low, language), high=format_money(high, language)
            ),
            send=BETWEEN[key].format(
                low=format_money(low, language), high=format_money(high, language)
            ),
        ),
        FollowUpOption(
            value=f"min:{high}",
            label=OVER[key].format(amount=format_money(high, language)),
            send=OVER[key].format(amount=format_money(high, language)),
        ),
    )


def follow_up(
    *,
    specification: SearchSpecification,
    matches: tuple[NormalizedProduct, ...],
    match_count: int,
    clarification: str | None,
    language: Language,
) -> FollowUp | None:
    """Build the one follow-up question worth asking, or nothing.

    ``matches`` is the ranked page the customer is about to see, and
    ``match_count`` is how many products satisfied every hard constraint, which
    can be larger. Options come from the page, because those are the products
    the question is about; the decision to ask at all comes from the count.

    ``clarification`` is the parser's own question, which is already in the
    customer's language and is preferred over a stock one because it refers to
    what they actually wrote.
    """

    hard = specification.hard
    key = response_language(language)

    if hard.category is None:
        # Nothing to choose from is not a question: with no matches the
        # response already explains what excluded them.
        if not matches:
            return None
        if clarification is None and match_count < MIN_BROAD_MATCHES:
            return None
        options = _category_options(matches, language)
        if len(options) < 2:
            return None
        return FollowUp(
            field="category",
            question=clarification or QUESTIONS["category"][key],
            options=options,
        )

    if hard.price is None and match_count >= MIN_BROAD_MATCHES:
        options = _price_options(matches, language)
        if not options:
            return None
        return FollowUp(
            field="price",
            question=clarification or QUESTIONS["price"][key],
            options=options,
        )

    return None
