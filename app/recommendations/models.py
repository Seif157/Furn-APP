"""Client-facing models for grounded reasons and alternatives (Phase 6)."""

from __future__ import annotations

from typing import Literal

from app.catalog.models import ProductResponse, StrictResponseModel


class ReasonResponse(StrictResponseModel):
    """One grounded statement about a product, in the customer's language.

    ``code`` is stable and machine-readable; ``text`` is display copy built
    from catalogue values. Section 6.6 of the master plan requires catalogue
    fact, inference, and aesthetic judgement to stay separate, so every reason
    here is the first kind: a number or a term the catalogue actually holds.
    """

    code: str
    text: str
    basis: Literal["catalogue", "inferred"] = "catalogue"
    """Which kind of statement this is.

    "catalogue" restates something the marketplace holds: a price, a width, a
    material, a colour in stock. "inferred" is the platform's own guess about
    style, room or feel, which no seller states. Section 6.6 requires the two
    to stay separate, so they are separate here rather than in the wording
    alone, and a client can style or hide a guess."""


class AlternativeResponse(StrictResponseModel):
    """A real product that missed, and exactly what it missed by.

    Offered only when nothing matched. Section 6.10 allows nearest real
    alternatives and forbids fabricating a product; these are catalogue rows
    that failed the fewest constraints, with the shortfall stated plainly so a
    customer can decide whether to relax.
    """

    product: ProductResponse
    missed: tuple[ReasonResponse, ...]
    missed_count: int
