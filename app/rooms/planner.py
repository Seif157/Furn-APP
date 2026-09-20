"""Choose one real product per slot so the room fits every stated budget.

Deterministic and exhaustive over a bounded space. Each slot keeps its best few
candidates, ranked by the same Phase 4D scoring search uses, and every
combination of those is costed. The winner is the best-scoring room within
budget, then the cheaper one, then product ids, so the same request always
gets the same room.

Two kinds of budget can apply at once. A customer may give one for a piece
("a sofa up to 12,000") and one for the whole room ("40,000 in total"). A room
is within budget only when every line is within its own budget and the total
is within the room's.

Quantity is real stock, not optimism. Two chairs means one chair model with at
least two in stock in a single colour, because a pair of chairs that arrives in
two colours is not what anyone asked for. The chosen colour is reported so the
customer knows which one to order.

When no combination fits, the room that is over by the least is returned and
the gap is stated, rather than a room missing pieces the customer asked for or
nothing at all. Never pretend, never go silent.

Upgrades are the answer to "is there something better for a little more?".
"Better" has to mean something checkable, so it means one thing only: the
option scores higher on what this customer asked for. A higher price is never
treated as better on its own.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.catalog.normalization import NormalizedColour, NormalizedProduct
from app.rooms.models import RoomSlot, RoomSpecification
from app.search.filters import constraint_checks, satisfies_all
from app.search.ranking import combine, score_parts
from app.search.results import ConstraintCheck, ScorePart

BEST_PER_SLOT = 4
CHEAPEST_PER_SLOT = 3
"""Each slot keeps its best-scoring few *and* its cheapest few.

Keeping only the best-scoring would be a correctness bug, not a tuning choice:
when the budget is tight, the room that fits may need a sofa that scores
sixth, and a planner that never considers it reports "over budget" for a room
that exists. At most seven candidates per slot and six slots is 117,649 rooms,
and a typical four-piece room is 2,401, both instant.
"""

UPGRADE_MARGIN = Decimal("0.15")
"""How far past a budget an upgrade may go and still count as "a little more".

Measured against the budget it would exceed: a line may reach 115% of its own
budget, and the room 115% of the room's. An option that needs more than that is
not a small stretch, so it is not offered.
"""
UPGRADES_PER_ITEM = 2

UnfilledReason = Literal["none_in_category", "material_unavailable", "not_enough_stock"]
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class Candidate:
    product: NormalizedProduct
    colour: NormalizedColour
    checks: tuple[ConstraintCheck, ...]
    score: Decimal
    parts: tuple[ScorePart, ...]


def line_total(candidate: Candidate, slot: RoomSlot) -> Decimal:
    return candidate.product.effective_price * slot.quantity


@dataclass(frozen=True, slots=True)
class Upgrade:
    """A better-matching option for one line, and what it would cost."""

    candidate: Candidate
    extra: Decimal
    """How much more this line would cost."""
    room_total: Decimal
    """The room's total with this upgrade and nothing else changed."""


@dataclass(frozen=True, slots=True)
class PlannedItem:
    slot: RoomSlot
    candidate: Candidate
    upgrades: tuple[Upgrade, ...] = ()

    @property
    def line_total(self) -> Decimal:
        return line_total(self.candidate, self.slot)

    @property
    def over_budget_by(self) -> Decimal | None:
        if self.slot.budget is None or self.line_total <= self.slot.budget:
            return None
        return self.line_total - self.slot.budget


@dataclass(frozen=True, slots=True)
class UnfilledSlot:
    slot: RoomSlot
    reason: UnfilledReason


@dataclass(frozen=True, slots=True)
class RoomPlan:
    items: tuple[PlannedItem, ...]
    unfilled: tuple[UnfilledSlot, ...]
    budget: Decimal | None

    @property
    def total(self) -> Decimal:
        return sum((item.line_total for item in self.items), ZERO)

    @property
    def within_budget(self) -> bool:
        """The whole room, against the room's budget."""

        return self.budget is None or self.total <= self.budget

    @property
    def every_line_within_budget(self) -> bool:
        return all(item.over_budget_by is None for item in self.items)


def _colour_for(product: NormalizedProduct, slot: RoomSlot) -> NormalizedColour | None:
    """A single colour with enough stock for the whole quantity, or none.

    Preferred colours first, then the most stock, so the choice is explainable
    and stable.
    """

    enough = [c for c in product.colours if c.stock_quantity >= slot.quantity]
    if not enough:
        return None
    preferred = set(slot.soft.colours)
    enough.sort(key=lambda c: (c.slug not in preferred, -c.stock_quantity))
    return enough[0]


def slot_options(
    products: tuple[NormalizedProduct, ...],
    slot: RoomSlot,
    specification: RoomSpecification,
) -> tuple[list[Candidate], UnfilledReason | None]:
    """Every product that could fill this slot, whatever it costs."""

    in_category = [p for p in products if p.category.slug == slot.category]
    if not in_category:
        return [], "none_in_category"

    matching: list[tuple[NormalizedProduct, tuple[ConstraintCheck, ...]]] = []
    for product in in_category:
        checks = constraint_checks(product, slot.hard)
        if satisfies_all(checks):
            matching.append((product, checks))
    if not matching:
        return [], "material_unavailable"

    found: list[Candidate] = []
    for product, checks in matching:
        colour = _colour_for(product, slot)
        if colour is None:
            continue
        # The room sentence itself is scored as the query, so a customer who
        # writes "مودرن" favours products whose own name says so, even while
        # the confirmed style attributes are empty.
        parts = score_parts(product, slot.soft, specification.scoring_query)
        found.append(Candidate(product, colour, checks, combine(parts), parts))
    if not found:
        return [], "not_enough_stock"
    return found, None


def _shortlist(candidates: list[Candidate], slot: RoomSlot) -> list[Candidate]:
    def fits(candidate: Candidate) -> bool:
        return slot.budget is None or line_total(candidate, slot) <= slot.budget

    # Best-scoring among those within the line's own budget first, so a strong
    # but unaffordable option cannot crowd out the one that fits.
    by_score = sorted(
        candidates,
        key=lambda c: (
            not fits(c),
            -c.score,
            c.product.effective_price,
            c.product.id.int,
        ),
    )
    by_price = sorted(
        candidates,
        key=lambda c: (c.product.effective_price, -c.score, c.product.id.int),
    )
    kept: dict = {}
    for candidate in (*by_score[:BEST_PER_SLOT], *by_price[:CHEAPEST_PER_SLOT]):
        kept.setdefault(candidate.product.id, candidate)
    return list(kept.values())


def _upgrades(
    item: PlannedItem,
    options: list[Candidate],
    *,
    room_total: Decimal,
    room_budget: Decimal | None,
) -> tuple[Upgrade, ...]:
    slot = item.slot
    if slot.budget is None and room_budget is None:
        # With no budget at all the planner already took the best match, so
        # anything scoring higher does not exist to offer.
        return ()

    current = item.line_total
    found: list[Upgrade] = []
    for option in options:
        if option.product.id == item.candidate.product.id:
            continue
        if option.score <= item.candidate.score:
            continue
        line = line_total(option, slot)
        if line <= current:
            continue
        new_total = room_total - current + line
        if slot.budget is not None and line > slot.budget * (1 + UPGRADE_MARGIN):
            continue
        if room_budget is not None and new_total > room_budget * (1 + UPGRADE_MARGIN):
            continue
        found.append(Upgrade(option, line - current, new_total))

    found.sort(key=lambda u: (-u.candidate.score, u.extra, u.candidate.product.id.int))
    return tuple(found[:UPGRADES_PER_ITEM])


def plan_room(
    products: Iterable[NormalizedProduct],
    specification: RoomSpecification,
) -> RoomPlan:
    catalogue = tuple(products)
    fillable: list[tuple[RoomSlot, list[Candidate], list[Candidate]]] = []
    unfilled: list[UnfilledSlot] = []

    for slot in specification.slots:
        options, reason = slot_options(catalogue, slot, specification)
        if reason is not None:
            unfilled.append(UnfilledSlot(slot, reason))
        else:
            fillable.append((slot, _shortlist(options, slot), options))

    if not fillable:
        return RoomPlan(items=(), unfilled=tuple(unfilled), budget=specification.budget)

    slots = [slot for slot, _, _ in fillable]
    budget = specification.budget
    best_key: tuple | None = None
    best_room: tuple[Candidate, ...] | None = None
    for room in itertools.product(*(short for _, short, _ in fillable)):
        lines = [line_total(c, s) for c, s in zip(room, slots, strict=True)]
        total = sum(lines, ZERO)
        line_overage = sum(
            (
                max(ZERO, line - s.budget)
                for line, s in zip(lines, slots, strict=True)
                if s.budget is not None
            ),
            ZERO,
        )
        room_overage = max(ZERO, total - budget) if budget is not None else ZERO
        mean_score = sum((c.score for c in room), ZERO) / len(room)
        ids = tuple(c.product.id.int for c in room)
        # Any room within every budget beats every room that is not. Among
        # those, the best-scoring wins, then the cheaper. Among the rest, the
        # smallest overage wins, because it is the smallest gap to explain.
        overage = line_overage + room_overage
        key = (
            (0, -mean_score, total, ids)
            if overage == ZERO
            else (1, overage, total, -mean_score, ids)
        )
        if best_key is None or key < best_key:
            best_key, best_room = key, room

    assert best_room is not None
    chosen = [
        PlannedItem(slot, candidate)
        for slot, candidate in zip(slots, best_room, strict=True)
    ]
    room_total = sum((item.line_total for item in chosen), ZERO)
    items = tuple(
        PlannedItem(
            item.slot,
            item.candidate,
            _upgrades(item, options, room_total=room_total, room_budget=budget),
        )
        for item, (_, _, options) in zip(chosen, fillable, strict=True)
    )
    return RoomPlan(items=items, unfilled=tuple(unfilled), budget=budget)
