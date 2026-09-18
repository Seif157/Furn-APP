"""Client-facing models for room plans and room preview images.

Every product in a plan goes through ``build_product_response``, the same
transform the catalogue endpoints use, so nothing the catalogue would withhold
reaches a client this way. Every number is a catalogue price times a quantity.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.catalog.models import ProductResponse, StrictResponseModel
from app.catalog.normalization import CATEGORIES
from app.catalog.transform import build_product_response
from app.catalog.upstream_models import UpstreamProduct
from app.recommendations.explanations import format_money, match_reasons
from app.recommendations.models import ReasonResponse
from app.rooms.models import MAX_ITEMS, MAX_QUANTITY, RoomSpecification
from app.rooms.planner import PlannedItem, RoomPlan, UnfilledReason
from app.rooms.upgrades import upgrade_reasons, upgrade_summary
from app.search.localization import response_language, term_label
from app.search.models import Language
from app.search.responses import TermResponse, UnresolvedResponse

UNFILLED_TEXT: dict[UnfilledReason, dict[str, str]] = {
    "none_in_category": {
        "en": "we do not carry this kind of furniture",
        "ar": "مش متوفر عندنا النوع ده",
    },
    "material_unavailable": {
        "en": "nothing in stock in that material",
        "ar": "مفيش حاجة متوفرة بالخامة دي",
    },
    "not_enough_stock": {
        "en": "not enough in stock in a single colour",
        "ar": "الكمية المطلوبة مش متوفرة بلون واحد",
    },
}
BUDGET_QUESTION = {
    "en": (
        "Would you like to set a budget for the whole room, or for each piece? "
        "We will pick the best match within it and point out anything better "
        "for a little more."
    ),
    "ar": (
        "تحب تحدد ميزانية للأوضة كلها أو لكل قطعة؟ هنختارلك أنسب حاجة في "
        "حدودها ونقولك لو فيه حاجة أحسن بفرق بسيط."
    ),
}
PREVIEW_LABEL = {
    "en": "AI preview",
    "ar": "معاينة بالذكاء الاصطناعي",
}
PREVIEW_DISCLAIMER = {
    "en": (
        "An illustration generated from the product photos. Details and "
        "proportions may differ from the real products, and the decor is for "
        "illustration only. The listed products are what you are buying."
    ),
    "ar": (
        "صورة توضيحية متولدة من صور المنتجات. التفاصيل والمقاسات ممكن تختلف "
        "عن المنتجات الحقيقية، والديكور والإكسسوارات للتوضيح بس. المنتجات "
        "اللي في القائمة هي اللي بتشتريها."
    ),
}


class _RequestModel(BaseModel):
    # Not strict: product ids arrive from JSON as strings, and strict mode
    # would refuse to read a string as a UUID. Unknown fields still fail.
    model_config = ConfigDict(extra="forbid", frozen=True)


class RoomImageItem(_RequestModel):
    product_id: UUID
    quantity: Annotated[int, Field(ge=1, le=MAX_QUANTITY)] = 1
    colour_id: UUID | None = None
    """The colour the plan chose. The preview uses that colour's own photo
    when there is one and names the colour to the model, so a plan that says
    grey is not illustrated by an orange sofa. Ignored unless it is a real
    colour of this product."""


class RoomImageRequest(_RequestModel):
    """Which real products to render. Ids only: the server looks each one up
    again under the caller's own token, so a client cannot render a product
    it could not have been shown, or describe a product that does not exist."""

    items: tuple[RoomImageItem, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    room_type: str | None = Field(default=None, max_length=40)
    styles: tuple[Annotated[str, Field(max_length=30)], ...] = Field(
        default=(), max_length=5
    )
    language: Literal["ar", "en"] = "en"


class UpgradeResponse(StrictResponseModel):
    """A better-matching option for one line, for a little more money.

    Offered only when it scores higher on what the customer asked for, and
    costs at most 15% past the budget it would exceed. ``reasons`` say exactly
    what it matches that the current pick does not; nothing here claims a
    product is nicer or of higher quality.
    """

    product: ProductResponse
    unit_price: Decimal
    line_total: Decimal
    extra_cost: Decimal
    colour: str
    room_total: Decimal
    """The room's total if this upgrade is taken and nothing else changes."""
    within_room_budget: bool | None
    """None when the customer set no budget for the room."""
    over_item_budget_by: Decimal | None
    reasons: tuple[ReasonResponse, ...]
    summary: str
    """One sentence to show as is, in the customer's language."""
    image_item: RoomImageItem
    """Swap this into image_request to preview the room with the upgrade."""


class RoomItemResponse(StrictResponseModel):
    requested: TermResponse
    """The kind of furniture the customer asked for."""
    product: ProductResponse
    quantity: int
    unit_price: Decimal
    """What one costs the customer: the discount price when there is one."""
    line_total: Decimal
    budget: Decimal | None
    """The budget the customer set for this line, all units together."""
    over_budget_by: Decimal | None
    colour: str
    """The catalogue colour to order, chosen because it has enough stock."""
    reasons: tuple[ReasonResponse, ...]
    upgrades: tuple[UpgradeResponse, ...]


class UnfilledResponse(StrictResponseModel):
    requested: TermResponse
    quantity: int
    reason: str
    text: str


class RoomPlanResponse(StrictResponseModel):
    query: str
    language: str
    items: tuple[RoomItemResponse, ...]
    total: Decimal
    budget: Decimal | None
    within_budget: bool
    """The room's total against the room's budget."""
    every_line_within_budget: bool
    """Every line against the budget the customer set for it, if any."""
    remaining: Decimal | None
    over_budget_by: Decimal | None
    summary: str
    """One sentence stating the total against the budget, in their language."""
    budget_question: str | None
    """Asked when the customer gave no budget at all. Not blocking: the plan
    is complete, this invites a budget so upgrades can be suggested."""
    unfilled: tuple[UnfilledResponse, ...]
    unresolved: tuple[UnresolvedResponse, ...]
    clarification: str | None
    image_request: RoomImageRequest | None
    """Exactly what to send to POST /v1/rooms/image to render this plan."""


class RoomImageResponse(StrictResponseModel):
    image_base64: str
    mime_type: str
    label: str
    """Show this on the image. It is a preview, not a product photograph."""
    disclaimer: str
    items: tuple[RoomImageItem, ...]
    references_used: int
    """How many real product photos the model was given to copy."""


def _term(slug: str, language: Language) -> TermResponse:
    return TermResponse(slug=slug, label=term_label(CATEGORIES, slug, language))


def _summary(plan: RoomPlan, language: Language) -> str:
    arabic = response_language(language) == "ar"
    pieces = sum(item.slot.quantity for item in plan.items)
    total = format_money(plan.total, language)
    if not plan.items:
        return (
            "مقدرناش نلاقي قطع متوفرة للأوضة دي"
            if arabic
            else "No pieces in stock match this room."
        )
    if plan.budget is None:
        sentence = (
            f"{pieces} قطع بإجمالي {total}"
            if arabic
            else f"{pieces} pieces for {total} in total"
        )
    elif plan.within_budget:
        budget = format_money(plan.budget, language)
        sentence = (
            f"{pieces} قطع بإجمالي {total}، في حدود ميزانيتك {budget}"
            if arabic
            else f"{pieces} pieces for {total}, within your {budget} budget"
        )
    else:
        over = format_money(plan.total - plan.budget, language)
        sentence = (
            f"أقرب اختيار لميزانيتك بإجمالي {total}، أكتر منها بـ {over}"
            if arabic
            else f"The closest room to your budget is {total}, {over} over your budget"
        )
    if not plan.every_line_within_budget:
        sentence += (
            "، وفيه قطع أغلى من الميزانية اللي حددتها ليها"
            if arabic
            else ", and some pieces cost more than the budget you set for them"
        )
    return sentence


def _upgrade_responses(
    planned: PlannedItem,
    *,
    by_id: dict,
    plan: RoomPlan,
    specification: RoomSpecification,
) -> tuple[UpgradeResponse, ...]:
    language = specification.language
    found: list[UpgradeResponse] = []
    for upgrade in planned.upgrades:
        product = by_id.get(upgrade.candidate.product.id)
        shown = build_product_response(product) if product is not None else None
        if shown is None:
            continue
        reasons = upgrade_reasons(
            planned.candidate,
            upgrade.candidate,
            slot=planned.slot,
            query=specification.scoring_query,
            language=language,
        )
        line = upgrade.candidate.product.effective_price * planned.slot.quantity
        found.append(
            UpgradeResponse(
                product=shown,
                unit_price=upgrade.candidate.product.effective_price,
                line_total=line,
                extra_cost=upgrade.extra,
                colour=upgrade.candidate.colour.original,
                room_total=upgrade.room_total,
                within_room_budget=(
                    None if plan.budget is None else upgrade.room_total <= plan.budget
                ),
                over_item_budget_by=(
                    line - planned.slot.budget
                    if planned.slot.budget is not None and line > planned.slot.budget
                    else None
                ),
                reasons=reasons,
                summary=upgrade_summary(
                    upgrade,
                    slot=planned.slot,
                    room_budget=plan.budget,
                    reasons=reasons,
                    language=language,
                ),
                image_item=RoomImageItem(
                    product_id=upgrade.candidate.product.id,
                    quantity=planned.slot.quantity,
                    colour_id=upgrade.candidate.colour.id,
                ),
            )
        )
    return tuple(found)


def build_room_plan_response(
    upstream: tuple[UpstreamProduct, ...],
    *,
    plan: RoomPlan,
    specification: RoomSpecification,
) -> RoomPlanResponse:
    language = specification.language
    by_id = {product.id: product for product in upstream}

    items: list[RoomItemResponse] = []
    colour_ids: list = []
    for planned in plan.items:
        product = by_id.get(planned.candidate.product.id)
        response = build_product_response(product) if product is not None else None
        if response is None:
            continue
        colour_ids.append(planned.candidate.colour.id)
        items.append(
            RoomItemResponse(
                requested=_term(planned.slot.category, language),
                product=response,
                quantity=planned.slot.quantity,
                unit_price=planned.candidate.product.effective_price,
                line_total=planned.line_total,
                budget=planned.slot.budget,
                over_budget_by=planned.over_budget_by,
                colour=planned.candidate.colour.original,
                reasons=match_reasons(
                    planned.candidate.checks, planned.slot.hard, language
                ),
                upgrades=_upgrade_responses(
                    planned, by_id=by_id, plan=plan, specification=specification
                ),
            )
        )

    lang = response_language(language)
    unfilled = tuple(
        UnfilledResponse(
            requested=_term(slot.slot.category, language),
            quantity=slot.slot.quantity,
            reason=slot.reason,
            text=UNFILLED_TEXT[slot.reason][lang],
        )
        for slot in plan.unfilled
    )
    over = (
        plan.total - plan.budget
        if plan.budget is not None and not plan.within_budget
        else None
    )
    remaining = (
        plan.budget - plan.total
        if plan.budget is not None and plan.within_budget
        else None
    )
    no_budget_given = plan.budget is None and all(
        slot.budget is None for slot in specification.slots
    )
    image_request = (
        RoomImageRequest(
            items=tuple(
                RoomImageItem(
                    product_id=item.product.id,
                    quantity=item.quantity,
                    colour_id=colour_id,
                )
                for item, colour_id in zip(items, colour_ids, strict=True)
            ),
            room_type=specification.room_type,
            styles=specification.styles[:5],
            language=lang,
        )
        if items
        else None
    )
    return RoomPlanResponse(
        query=specification.query.original,
        language=lang,
        items=tuple(items),
        total=plan.total,
        budget=plan.budget,
        within_budget=plan.within_budget,
        every_line_within_budget=plan.every_line_within_budget,
        remaining=remaining,
        over_budget_by=over,
        summary=_summary(plan, language),
        budget_question=(
            BUDGET_QUESTION[lang] if no_budget_given and specification.slots else None
        ),
        unfilled=unfilled,
        unresolved=tuple(
            UnresolvedResponse(field=term.field, surface=term.surface)
            for term in specification.unresolved
        ),
        clarification=specification.clarification,
        image_request=image_request,
    )


__all__ = [
    "MAX_QUANTITY",
    "PREVIEW_DISCLAIMER",
    "PREVIEW_LABEL",
    "RoomImageItem",
    "RoomImageRequest",
    "RoomImageResponse",
    "RoomPlanResponse",
    "build_room_plan_response",
]
