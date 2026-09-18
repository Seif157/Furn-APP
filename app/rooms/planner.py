"""Choose one real product per slot so the whole room fits the budget.

Deterministic and exhaustive over a bounded space. Each slot keeps its best few
candidates, ranked by the same Phase 4D scoring search uses, and every
combination of those is costed. The winner is the best-scoring room within
budget, then the cheaper one, then product ids, so the same request always
gets the same room.

Quantity is real stock, not optimism. Two chairs means one chair model with at
least two in stock in a single colour, because a pair of chairs that arrives in
two colours is not what anyone asked for. The chosen colour is reported so the
customer knows which one to order.

When no combination fits the budget, the cheapest room is returned with the
amount it is over, rather than a room missing pieces the customer asked for or
nothing at all. Being honest about the gap is the same rule as nearest
alternatives: never pretend, never go silent.
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
from app.search.results import ConstraintCheck

BEST_PER_SLOT = 4
CHEAPEST_PER_SLOT = 3
"""Each slot keeps its best-scoring few *and* its cheapest few.

Keeping only the best-scoring would be a correctness bug, not a tuning choice:
when the budget is tight, the room that fits may need a sofa that scores
sixth, and a planner that never considers it reports "over budget" for a room
that exists. At most seven candidates per slot and six slots is 117,649 rooms,
and a typical four-piece room is 2,401, both instant.
"""

UnfilledReason = Literal["none_in_category", "material_unavailable", "not_enough_stock"]


@dataclass(frozen=True, slots=True)
class Candidate:
    product: NormalizedProduct
    colour: NormalizedColour
    checks: tuple[ConstraintCheck, ...]
    score: Decimal


@dataclass(frozen=True, slots=True)
class PlannedItem:
    slot: RoomSlot
    candidate: Candidate

    @property
    def line_total(self) -> Decimal:
        return self.candidate.product.effective_price * self.slot.quantity


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
        return sum((item.line_total for item in self.items), Decimal("0"))

    @property
    def within_budget(self) -> bool:
        return self.budget is None or self.total <= self.budget


def _colour_for(product: NormalizedProduct, slot: RoomSlot) -> NormalizedColour | None:
    """A single colour with enough stock for the whole quantity, or none.

    Preferred colours first, then the most stock, then the catalogue's own
    order, so the choice is explainable and stable.
    """

    enough = [c for c in product.colours if c.stock_quantity >= slot.quantity]
    if not enough:
        return None
    preferred = set(slot.soft.colours)
    enough.sort(key=lambda c: (c.slug not in preferred, -c.stock_quantity))
    return enough[0]


def _candidates(
    products: tuple[NormalizedProduct, ...],
    slot: RoomSlot,
    specification: RoomSpecification,
) -> tuple[list[Candidate], UnfilledReason | None]:
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
        score = combine(score_parts(product, slot.soft, specification.query))
        found.append(Candidate(product, colour, checks, score))
    if not found:
        return [], "not_enough_stock"

    by_score = sorted(
        found, key=lambda c: (-c.score, c.product.effective_price, c.product.id.int)
    )
    by_price = sorted(
        found, key=lambda c: (c.product.effective_price, -c.score, c.product.id.int)
    )
    kept: dict = {}
    for candidate in (*by_score[:BEST_PER_SLOT], *by_price[:CHEAPEST_PER_SLOT]):
        kept.setdefault(candidate.product.id, candidate)
    return list(kept.values()), None


def plan_room(
    products: Iterable[NormalizedProduct],
    specification: RoomSpecification,
) -> RoomPlan:
    catalogue = tuple(products)
    fillable: list[tuple[RoomSlot, list[Candidate]]] = []
    unfilled: list[UnfilledSlot] = []

    for slot in specification.slots:
        candidates, reason = _candidates(catalogue, slot, specification)
        if reason is not None:
            unfilled.append(UnfilledSlot(slot, reason))
        else:
            fillable.append((slot, candidates))

    if not fillable:
        return RoomPlan(items=(), unfilled=tuple(unfilled), budget=specification.budget)

    slots = [slot for slot, _ in fillable]
    best_key: tuple | None = None
    best_room: tuple[Candidate, ...] | None = None
    for room in itertools.product(*(candidates for _, candidates in fillable)):
        total = sum(
            (
                c.product.effective_price * s.quantity
                for c, s in zip(room, slots, strict=True)
            ),
            Decimal("0"),
        )
        fits = specification.budget is None or total <= specification.budget
        mean_score = sum((c.score for c in room), Decimal("0")) / len(room)
        ids = tuple(c.product.id.int for c in room)
        # Any room that fits beats every room that does not. Among rooms that
        # fit, the best-scoring wins, then the cheaper. Among rooms that do
        # not, the cheapest wins, because it is the smallest gap to explain.
        key = (0, -mean_score, total, ids) if fits else (1, total, -mean_score, ids)
        if best_key is None or key < best_key:
            best_key, best_room = key, room

    assert best_room is not None
    return RoomPlan(
        items=tuple(
            PlannedItem(slot, candidate)
            for slot, candidate in zip(slots, best_room, strict=True)
        ),
        unfilled=tuple(unfilled),
        budget=specification.budget,
    )
