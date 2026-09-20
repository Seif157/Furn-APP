"""Explain an upgrade in facts: what it matches that the current pick does not.

An upgrade is only ever offered because it scores higher on what the customer
asked for, so its reasons are read from exactly the score components where it
beats the current pick. Each reason names the concrete thing: the customer's
own words the product's listing contains, a preferred colour it is in stock in,
a size closer to the one they asked for. No reason says "nicer", "premium" or
"better quality", because nothing in the catalogue measures those, and section
6.6 of the master plan forbids presenting judgement as fact.
"""

from __future__ import annotations

from decimal import Decimal

from app.catalog.normalization import COLOURS
from app.recommendations.explanations import format_money
from app.recommendations.models import ReasonResponse
from app.rooms.models import RoomSlot
from app.rooms.planner import Candidate, Upgrade
from app.search.localization import response_language, term_label
from app.search.models import Language, QueryText
from app.search.ranking import matched_query_words


def _values(candidate: Candidate) -> dict[str, Decimal]:
    return {part.component: part.value for part in candidate.parts}


def upgrade_reasons(
    current: Candidate,
    upgrade: Candidate,
    *,
    slot: RoomSlot,
    query: QueryText,
    language: Language,
) -> tuple[ReasonResponse, ...]:
    arabic = response_language(language) == "ar"
    before, after = _values(current), _values(upgrade)
    reasons: list[ReasonResponse] = []

    if after.get("query", Decimal(0)) > before.get("query", Decimal(0)):
        new_words = [
            word
            for word in matched_query_words(upgrade.product, query)
            if word not in matched_query_words(current.product, query)
        ][:3]
        if new_words:
            quoted = (
                "، ".join(f"«{w}»" for w in new_words)
                if arabic
                else ", ".join(f"“{w}”" for w in new_words)
            )
            reasons.append(
                ReasonResponse(
                    code="query",
                    text=(
                        f"بيطابق {quoted} اللي طلبته"
                        if arabic
                        else f"matches {quoted} from your request"
                    ),
                )
            )

    if after.get("colours", Decimal(0)) > before.get("colours", Decimal(0)):
        in_stock = {
            c.slug for c in upgrade.product.colours if c.stock_quantity >= slot.quantity
        }
        labels = [
            term_label(COLOURS, slug, language)
            for slug in slot.soft.colours
            if slug in in_stock
        ]
        if labels:
            joined = "، ".join(labels) if arabic else ", ".join(labels)
            reasons.append(
                ReasonResponse(
                    code="colours",
                    text=(
                        f"متوفر باللون اللي بتفضله: {joined}"
                        if arabic
                        else f"in your preferred colour: {joined}"
                    ),
                )
            )

    if after.get("styles", Decimal(0)) > before.get("styles", Decimal(0)):
        reasons.append(
            ReasonResponse(
                code="styles",
                text="بيطابق الستايل اللي طلبته" if arabic else "matches your style",
            )
        )

    if any(
        after.get(axis, Decimal(0)) > before.get(axis, Decimal(0))
        for axis in ("width", "height", "depth")
    ):
        reasons.append(
            ReasonResponse(
                code="size",
                text=(
                    "أقرب للمقاس اللي طلبته"
                    if arabic
                    else "closer to the size you asked for"
                ),
            )
        )

    return tuple(reasons)


def upgrade_summary(
    upgrade: Upgrade,
    *,
    slot: RoomSlot,
    room_budget: Decimal | None,
    reasons: tuple[ReasonResponse, ...],
    language: Language,
) -> str:
    """One sentence: what it costs, why it is better, what it does to budgets."""

    arabic = response_language(language) == "ar"
    extra = format_money(upgrade.extra, language)
    why = (
        "، ".join(r.text for r in reasons)
        if arabic
        else "; ".join(r.text for r in reasons)
    )

    effects: list[str] = []
    line = upgrade.candidate.product.effective_price * slot.quantity
    if slot.budget is not None and line > slot.budget:
        over = format_money(line - slot.budget, language)
        effects.append(
            f"أكتر من ميزانية القطعة بـ {over}"
            if arabic
            else f"{over} over your budget for this piece"
        )
    if room_budget is not None:
        if upgrade.room_total <= room_budget:
            effects.append(
                "والأوضة تفضل في حدود ميزانيتك"
                if arabic
                else "and the room stays within your budget"
            )
        else:
            over = format_money(upgrade.room_total - room_budget, language)
            effects.append(
                f"والأوضة تعدي ميزانيتك بـ {over}"
                if arabic
                else f"and the room goes {over} over your budget"
            )

    if arabic:
        sentence = f"بزيادة {extra}"
        if why:
            sentence += f": {why}"
        if effects:
            sentence += "، " + "، ".join(effects)
        return sentence
    sentence = f"For {extra} more"
    if why:
        sentence += f": {why}"
    if effects:
        sentence += ", " + ", ".join(effects)
    return sentence
