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
from app.rooms.planner import RoomPlan, UnfilledReason
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
PREVIEW_LABEL = {
    "en": "AI preview",
    "ar": "معاينة بالذكاء الاصطناعي",
}
PREVIEW_DISCLAIMER = {
    "en": (
        "An illustration generated from the product photos. Details and "
        "proportions may differ from the real products; the product photos "
        "and listings are what you are buying."
    ),
    "ar": (
        "صورة توضيحية متولدة من صور المنتجات. التفاصيل والمقاسات ممكن تختلف "
        "عن المنتجات الحقيقية، والمنتجات بصورها ومواصفاتها هي اللي بتشتريها."
    ),
}


class RoomItemResponse(StrictResponseModel):
    requested: TermResponse
    """The kind of furniture the customer asked for."""
    product: ProductResponse
    quantity: int
    unit_price: Decimal
    """What one costs the customer: the discount price when there is one."""
    line_total: Decimal
    colour: str
    """The catalogue colour to order, chosen because it has enough stock."""
    reasons: tuple[ReasonResponse, ...]


class UnfilledResponse(StrictResponseModel):
    requested: TermResponse
    quantity: int
    reason: str
    text: str


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


class RoomPlanResponse(StrictResponseModel):
    query: str
    language: str
    items: tuple[RoomItemResponse, ...]
    total: Decimal
    budget: Decimal | None
    within_budget: bool
    remaining: Decimal | None
    over_budget_by: Decimal | None
    summary: str
    """One sentence stating the total against the budget, in their language."""
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
        return (
            f"{pieces} قطع بإجمالي {total}"
            if arabic
            else f"{pieces} pieces for {total} in total"
        )
    budget = format_money(plan.budget, language)
    if plan.within_budget:
        return (
            f"{pieces} قطع بإجمالي {total}، في حدود ميزانيتك {budget}"
            if arabic
            else f"{pieces} pieces for {total}, within your {budget} budget"
        )
    over = format_money(plan.total - plan.budget, language)
    return (
        f"أرخص اختيار متاح بإجمالي {total}، أكتر من ميزانيتك بـ {over}"
        if arabic
        else f"The cheapest available room is {total}, {over} over your budget"
    )


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
                colour=planned.candidate.colour.original,
                reasons=match_reasons(
                    planned.candidate.checks, planned.slot.hard, language
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
        remaining=remaining,
        over_budget_by=over,
        summary=_summary(plan, language),
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
