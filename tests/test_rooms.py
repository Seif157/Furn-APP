"""Room parsing and planning. No provider is contacted."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.ai.provider import AIResponseInvalidError
from app.ai.service import InvalidQueryError
from app.rooms import planner as planner_module
from app.rooms.models import RoomDraft, RoomItemDraft
from app.rooms.parser import (
    RoomDraftError,
    parse_room_request,
    specification_from_room_draft,
)
from app.rooms.planner import plan_room
from app.rooms.prompts import ROOM_INSTRUCTION, ROOM_SCHEMA, Piece, image_prompt
from tests import evaluation as ev

ARABIC_ROOM = "عايز أوضة فيها كنبة و2 كرسي وترابيزة في حدود 40 ألف"
ARABIC_DRAFT: dict[str, Any] = {
    "items": [
        {"category": "كنبة"},
        {"category": "كرسي", "quantity": 2},
        {"category": "ترابيزة"},
    ],
    "max_budget": 40000,
}


@pytest.fixture(scope="module")
def catalogue() -> tuple:
    return ev.eligible_catalogue()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def spec(draft: dict[str, Any], query: str = "a room"):
    return specification_from_room_draft(RoomDraft.model_validate(draft), query=query)


class StubProvider:
    def __init__(self, answer: Mapping[str, Any]) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    async def generate_json(self, *, instruction, prompt, schema):
        self.calls.append(
            {"instruction": instruction, "prompt": prompt, "schema": schema}
        )
        return self.answer


# --- the draft ---------------------------------------------------------------


def test_a_room_draft_can_carry_no_marketplace_fact() -> None:
    assert set(RoomDraft.model_fields) == {
        "items",
        "max_budget",
        "styles",
        "preferred_colours",
        "room_type",
        "clarification_question",
    }
    assert set(RoomItemDraft.model_fields) == {
        "category",
        "quantity",
        "colours",
        "materials",
        "max_budget",
    }
    assert set(ROOM_SCHEMA["properties"]) == set(RoomDraft.model_fields)
    item_schema = ROOM_SCHEMA["properties"]["items"]["items"]["properties"]
    assert set(item_schema) == set(RoomItemDraft.model_fields)


@pytest.mark.parametrize("quantity", [0, -1, 11])
def test_an_impossible_quantity_is_refused(quantity: int) -> None:
    with pytest.raises(ValidationError):
        RoomDraft.model_validate(
            {"items": [{"category": "sofa", "quantity": quantity}]}
        )


def test_the_instruction_asks_for_the_customers_own_word() -> None:
    assert "Copy" in ROOM_INSTRUCTION and "their word" in ROOM_INSTRUCTION
    assert "كرسيين" in ROOM_INSTRUCTION


# --- guardrails ---------------------------------------------------------------


def test_the_arabic_example_becomes_three_slots_and_a_budget() -> None:
    room = spec(ARABIC_DRAFT, ARABIC_ROOM)

    assert [(s.category, s.quantity) for s in room.slots] == [
        ("sofas", 1),
        ("chairs", 2),
        ("dining", 1),
    ]
    assert room.budget == Decimal("40000")
    assert room.language == "ar"
    assert room.unresolved == ()


def test_a_bare_table_means_a_dining_table_but_a_coffee_table_does_not() -> None:
    room = spec(
        {"items": [{"category": "table"}, {"category": "coffee table"}]},
    )

    assert [s.category for s in room.slots] == ["dining"]
    assert [t.surface for t in room.unresolved] == ["coffee table"]


def test_the_same_kind_of_furniture_twice_is_one_slot() -> None:
    room = spec(
        {
            "items": [
                {"category": "chair", "quantity": 2},
                {"category": "كرسي", "quantity": 1},
            ]
        }
    )

    assert [(s.category, s.quantity) for s in room.slots] == [("chairs", 3)]


def test_a_merged_quantity_past_the_limit_is_refused() -> None:
    with pytest.raises(RoomDraftError):
        spec(
            {
                "items": [
                    {"category": "chair", "quantity": 6},
                    {"category": "كرسي", "quantity": 6},
                ]
            }
        )


@pytest.mark.parametrize("budget", [0, -5, 1e12])
def test_an_impossible_budget_rejects_the_draft(budget: float) -> None:
    with pytest.raises(RoomDraftError):
        spec({"items": [{"category": "sofa"}], "max_budget": budget})


def test_unknown_words_are_reported_never_guessed() -> None:
    room = spec(
        {
            "items": [
                {
                    "category": "sofa",
                    "colours": ["turquoise"],
                    "materials": ["unobtainium"],
                }
            ],
            "preferred_colours": ["glitter"],
        }
    )

    surfaces = {t.surface for t in room.unresolved}
    assert surfaces == {"turquoise", "unobtainium", "glitter"}
    assert room.slots[0].hard.materials == ()


def test_room_colours_and_styles_reach_every_slot() -> None:
    room = spec(
        {
            "items": [{"category": "sofa", "colours": ["grey"]}, {"category": "chair"}],
            "preferred_colours": ["beige"],
            "styles": ["Modern"],
        }
    )

    assert room.slots[0].soft.colours == ("grey", "beige")
    assert room.slots[1].soft.colours == ("beige",)
    assert all(s.soft.styles == ("modern",) for s in room.slots)


@pytest.mark.anyio
async def test_parsing_sends_the_backend_instruction_and_the_trimmed_sentence() -> None:
    provider = StubProvider(ARABIC_DRAFT)

    room = await parse_room_request(f"  {ARABIC_ROOM}  ", provider=provider)

    (call,) = provider.calls
    assert call["instruction"] == ROOM_INSTRUCTION
    assert call["schema"] == ROOM_SCHEMA
    assert call["prompt"] == ARABIC_ROOM
    assert len(room.slots) == 3


@pytest.mark.anyio
async def test_a_malformed_room_draft_is_an_invalid_response() -> None:
    provider = StubProvider({"items": "a sofa please"})

    with pytest.raises(AIResponseInvalidError):
        await parse_room_request("a sofa", provider=provider)


@pytest.mark.anyio
async def test_empty_input_is_refused_before_a_call() -> None:
    provider = StubProvider(ARABIC_DRAFT)

    with pytest.raises(InvalidQueryError):
        await parse_room_request("   ", provider=provider)
    assert provider.calls == []


# --- the planner --------------------------------------------------------------


def test_the_plan_fits_the_budget_and_adds_up(catalogue) -> None:
    room = spec(ARABIC_DRAFT, ARABIC_ROOM)

    plan = plan_room(catalogue, room)

    assert len(plan.items) == 3
    assert plan.within_budget
    assert plan.total <= Decimal("40000")
    assert plan.total == sum(
        item.candidate.product.effective_price * item.slot.quantity
        for item in plan.items
    )


def test_every_piece_is_in_stock_in_one_colour_for_its_whole_quantity(
    catalogue,
) -> None:
    plan = plan_room(catalogue, spec(ARABIC_DRAFT, ARABIC_ROOM))

    for item in plan.items:
        assert item.candidate.colour.stock_quantity >= item.slot.quantity
        assert item.candidate.product.category.slug == item.slot.category


def test_a_stated_style_makes_the_room_coherent(catalogue) -> None:
    room = spec(
        {
            "items": [
                {"category": "sofa"},
                {"category": "chair", "quantity": 2},
                {"category": "table"},
            ],
            "max_budget": 30000,
            "styles": ["modern"],
        },
        "modern living room: sofa, 2 chairs, table, under 30000",
    )

    plan = plan_room(catalogue, room)

    assert plan.within_budget
    for item in plan.items:
        description = item.candidate.product.description
        assert description is not None and "modern" in description.normalized


def test_a_preferred_colour_is_chosen_when_there_is_enough_of_it(catalogue) -> None:
    room = spec(
        {"items": [{"category": "sofa", "colours": ["grey"]}], "styles": ["modern"]}
    )

    plan = plan_room(catalogue, room)

    (item,) = plan.items
    assert item.candidate.colour.slug == "grey"


def test_an_unaffordable_room_is_the_cheapest_one_and_says_so(catalogue) -> None:
    room = spec(
        {
            "items": [{"category": "sofa"}, {"category": "chair", "quantity": 4}],
            "max_budget": 10000,
        }
    )

    plan = plan_room(catalogue, room)

    assert not plan.within_budget
    assert len(plan.items) == 2, "every requested piece is still planned"
    cheapest_sofa = min(
        p.effective_price for p in catalogue if p.category.slug == "sofas"
    )
    assert plan.items[0].candidate.product.effective_price == cheapest_sofa


def test_the_cheapest_option_is_considered_even_when_it_scores_low(
    catalogue, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The bug this guards: keeping only the best-scoring candidates means a
    # tight budget can be reported unaffordable while a fitting room exists.
    # With one best-scoring candidate per slot, "classic" favours the 16,575
    # classic sofa; only the cheapest-candidates rule can still find the 9,900
    # one that fits.
    monkeypatch.setattr(planner_module, "BEST_PER_SLOT", 1)
    room = spec(
        {"items": [{"category": "sofa"}], "max_budget": 10000},
        "كنبة كلاسيك",
    )

    plan = plan_room(catalogue, room)

    assert plan.within_budget
    assert plan.items[0].candidate.product.effective_price <= Decimal("10000")


def test_a_quantity_no_colour_can_supply_is_reported_not_split(catalogue) -> None:
    plan = plan_room(
        catalogue, spec({"items": [{"category": "office chair", "quantity": 5}]})
    )

    assert plan.items == ()
    (unfilled,) = plan.unfilled
    assert unfilled.reason == "not_enough_stock"


def test_an_unavailable_material_is_reported(catalogue) -> None:
    plan = plan_room(
        catalogue, spec({"items": [{"category": "sofa", "materials": ["marble"]}]})
    )

    (unfilled,) = plan.unfilled
    assert unfilled.reason == "material_unavailable"


def test_a_category_with_nothing_in_it_is_reported(catalogue) -> None:
    without_beds = tuple(p for p in catalogue if p.category.slug != "beds")

    plan = plan_room(
        without_beds, spec({"items": [{"category": "bed"}, {"category": "sofa"}]})
    )

    assert [u.reason for u in plan.unfilled] == ["none_in_category"]
    assert [i.slot.category for i in plan.items] == ["sofas"]


def test_the_same_request_always_plans_the_same_room(catalogue) -> None:
    room = spec(ARABIC_DRAFT, ARABIC_ROOM)

    first = plan_room(catalogue, room)
    second = plan_room(tuple(reversed(catalogue)), room)

    assert [i.candidate.product.id for i in first.items] == [
        i.candidate.product.id for i in second.items
    ]


def test_every_planned_product_is_a_real_catalogue_row(catalogue) -> None:
    ids = {p.id for p in catalogue}
    plan = plan_room(catalogue, spec(ARABIC_DRAFT, ARABIC_ROOM))

    assert all(item.candidate.product.id in ids for item in plan.items)


# --- the image prompt ---------------------------------------------------------


def test_the_image_prompt_names_every_piece_against_its_own_photo() -> None:
    prompt = image_prompt(
        pieces=[
            Piece(1, "sofas", "كنبة مودرن", colour="grey", photo=1),
            Piece(2, "chairs", "كرسي سفرة", photo=2),
        ],
        room_type="living room",
        styles=("modern",),
    )

    assert "interior photograph of a modern living room" in prompt
    assert (
        "one x sofas (كنبة مودرن), in grey: reproduce it from reference photograph 1"
        in prompt
    )
    assert (
        "exactly 2 x chairs (كرسي سفرة): reproduce it from reference photograph 2"
        in prompt
    )
    assert "Do not add any other seating, tables, beds or storage" in prompt
    assert "No people, no text" in prompt


def test_a_piece_without_a_photo_does_not_shift_the_others() -> None:
    # The bug this guards: numbering photos by position means one skipped
    # photo moves every later piece onto the wrong reference.
    prompt = image_prompt(
        pieces=[
            Piece(1, "sofas", "A", photo=None),
            Piece(1, "chairs", "B", photo=1),
        ],
        room_type=None,
        styles=(),
    )

    assert "one x sofas (A): no photograph is available" in prompt
    assert "one x chairs (B): reproduce it from reference photograph 1" in prompt
    assert "photograph 2" not in prompt


# --- budgets per piece ------------------------------------------------------------

MODERN_SOFA_SENTENCE = "عايز كنبة مودرن في حدود 12 ألف"


def test_a_budget_for_one_piece_becomes_that_lines_budget() -> None:
    room = spec(
        {
            "items": [
                {"category": "sofa", "max_budget": 12000},
                {"category": "chair", "quantity": 2, "max_budget": 3000},
            ],
            "max_budget": 25000,
        }
    )

    assert [s.budget for s in room.slots] == [Decimal("12000"), Decimal("3000")]
    assert room.budget == Decimal("25000")


def test_merged_lines_add_their_budgets_only_when_every_part_had_one() -> None:
    both = spec(
        {
            "items": [
                {"category": "chair", "max_budget": 1500},
                {"category": "كرسي", "max_budget": 2000},
            ]
        }
    )
    one = spec(
        {"items": [{"category": "chair", "max_budget": 1500}, {"category": "كرسي"}]}
    )

    assert both.slots[0].budget == Decimal("3500")
    # Half a budget is not a budget for the whole line, so none is invented.
    assert one.slots[0].budget is None


@pytest.mark.parametrize("budget", [0, -1, 1e12])
def test_an_impossible_piece_budget_rejects_the_draft(budget: float) -> None:
    with pytest.raises(RoomDraftError):
        spec({"items": [{"category": "sofa", "max_budget": budget}]})


def test_a_piece_budget_is_respected_when_something_fits(catalogue) -> None:
    room = spec(
        {"items": [{"category": "كنبة", "max_budget": 12000}], "styles": ["modern"]},
        MODERN_SOFA_SENTENCE,
    )

    plan = plan_room(catalogue, room)

    (item,) = plan.items
    assert item.line_total <= Decimal("12000")
    assert item.over_budget_by is None
    assert plan.every_line_within_budget


def test_a_piece_nothing_can_satisfy_is_the_closest_and_says_by_how_much(
    catalogue,
) -> None:
    room = spec({"items": [{"category": "sofa", "max_budget": 1000}]})

    plan = plan_room(catalogue, room)

    (item,) = plan.items
    cheapest = min(p.effective_price for p in catalogue if p.category.slug == "sofas")
    assert item.line_total == cheapest
    assert item.over_budget_by == cheapest - Decimal("1000")
    assert not plan.every_line_within_budget


# --- upgrades -----------------------------------------------------------------


def test_a_better_match_just_past_a_piece_budget_is_offered(catalogue) -> None:
    # The modern sofa costs 13,500: over a 12,000 budget, but within 15% of it,
    # and it is the only sofa whose own listing says "مودرن".
    room = spec(
        {"items": [{"category": "كنبة", "max_budget": 12000}], "styles": ["modern"]},
        MODERN_SOFA_SENTENCE,
    )

    (item,) = plan_room(catalogue, room).items

    (upgrade,) = item.upgrades
    assert "مودرن" in upgrade.candidate.product.name.original
    assert upgrade.candidate.score > item.candidate.score
    assert upgrade.extra == upgrade.candidate.product.effective_price - item.line_total


def test_nothing_is_offered_beyond_the_small_margin(catalogue) -> None:
    # 13,500 is more than 15% past 11,000, so it is not "a little more".
    room = spec(
        {"items": [{"category": "كنبة", "max_budget": 11000}], "styles": ["modern"]},
        MODERN_SOFA_SENTENCE,
    )

    (item,) = plan_room(catalogue, room).items

    assert item.upgrades == ()


def test_without_any_budget_there_is_nothing_better_to_offer(catalogue) -> None:
    # With no budget the planner already takes the best match.
    room = spec({"items": [{"category": "كنبة"}], "styles": ["modern"]}, "كنبة مودرن")

    (item,) = plan_room(catalogue, room).items

    assert "مودرن" in item.candidate.product.name.original
    assert item.upgrades == ()


@pytest.mark.parametrize("room_budget", [15000, 20000, 25000, 30000])
def test_every_upgrade_obeys_the_rules(catalogue, room_budget: int) -> None:
    room = spec(
        {
            "items": [
                {"category": "sofa"},
                {"category": "chair", "quantity": 2},
                {"category": "table"},
            ],
            "max_budget": room_budget,
            "styles": ["modern"],
        },
        "أوضة مودرن فيها كنبة و2 كرسي وترابيزة",
    )

    plan = plan_room(catalogue, room)

    for item in plan.items:
        for upgrade in item.upgrades:
            line = upgrade.candidate.product.effective_price * item.slot.quantity
            assert upgrade.candidate.score > item.candidate.score
            assert line > item.line_total
            assert upgrade.room_total == plan.total - item.line_total + line
            assert upgrade.room_total <= Decimal(room_budget) * Decimal("1.15")
            assert upgrade.candidate.product.category.slug == item.slot.category
            assert upgrade.candidate.colour.stock_quantity >= item.slot.quantity


def test_filler_words_in_a_request_never_count_as_a_match(catalogue) -> None:
    # Found live: "13000 in total" let a leather sofa tie with the modern sofa
    # the customer asked for, because its description contains "in". An
    # upgrade reason would then have claimed it "matches “in”".
    from app.search.models import query_text
    from app.search.ranking import matched_query_words

    query = query_text("a modern sofa, 12000 for the sofa and 13000 in total")
    for product in catalogue:
        words = set(matched_query_words(product, query))
        assert not words & {"in", "for", "the", "and", "total", "a"}
    arabic = query_text("عايز كنبة مودرن في حدود 12 ألف")
    for product in catalogue:
        assert not set(matched_query_words(product, arabic)) & {"في", "حدود", "عايز"}
