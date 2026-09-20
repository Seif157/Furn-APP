"""The room-request instruction, its response schema, and the image prompt.

The instruction applies the two rules Phase 5D and Phase 6 measured into the
search prompt. The model copies the customer's own word for each piece rather
than choosing from a list, because choosing is where it copied the wrong entry.
And a described colour is a preference while a named material is a
requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ai.models import MAX_QUESTION_LENGTH, MAX_SURFACE_LENGTH
from app.rooms.models import MAX_ITEMS, MAX_QUANTITY, RoomDraft, RoomItemDraft
from app.search.models import MAX_TERMS

ROOM_INSTRUCTION = f"""\
You read a furniture shopper's description of a room they want to furnish. You
work for a furniture marketplace in Egypt. Customers write in Arabic, in
English, or in a mix of both.

Return only what the sentence actually says. Never guess a budget, a piece of
furniture, a colour, or a material the customer did not mention.

items lists each kind of furniture they asked for, with how many.

  category is the customer's own word for the piece, in the singular. Copy
  their word: "كنبة", "كرسي", "ترابيزة", "sofa", "chair", "table". Do not
  replace it with a different word, and never add a piece they did not ask for.
  quantity is how many of that piece. "كرسيين" and "2 كرسي" and "two chairs"
  are all one item with category "كرسي" or "chair" and quantity 2. Use 1 when
  no number is given. At most {MAX_QUANTITY}.
  List each kind of furniture once. At most {MAX_ITEMS} kinds.

  A colour the customer attaches to one piece goes in that item's colours, as
  a preference. A material they attach to one piece goes in that item's
  materials, as a requirement.

  A budget the customer gives for one piece goes in that item's max_budget, as
  the total for that line. When they give a price per piece, multiply it by the
  quantity: "2 كرسي بـ 1500 للواحد" and "two chairs at 1500 each" are
  max_budget 3000. When they give one amount for several pieces together,
  such as "2 كرسي في حدود 3000", use it as it is.

max_budget at the top level is the total the customer wants to spend on the
whole room. Read "40 ألف", "٤٠ ألف", "40k" and "40,000" all as 40000. Ignore
the currency word. Omit any budget that is not stated; never invent one. Never
return a negative or zero number.

styles and preferred_colours describe the whole room, for example "أوضة مودرن"
or "a beige living room". Write styles in English, lowercase: "modern",
"classic", "scandinavian", "industrial".

room_type is the kind of room in English, lowercase, for example
"living room", "bedroom", "dining room". Omit it when not stated.

At most {MAX_TERMS} entries in any list, at most {MAX_SURFACE_LENGTH}
characters in any word or phrase.

Set clarification_question only when the customer named no furniture at all,
such as "عايز أفرش شقتي". Ask one short question, under {MAX_QUESTION_LENGTH}
characters. If their sentence contains any Arabic, write it in Egyptian
Arabic; otherwise in English.

You never see the catalogue. You never name a product, a seller, a price that
exists, or a stock level. You only restate what the customer asked for.
"""

_SURFACE: dict[str, Any] = {
    "type": "STRING",
    "nullable": True,
    "maxLength": MAX_SURFACE_LENGTH,
}
_SURFACE_LIST: dict[str, Any] = {
    "type": "ARRAY",
    "maxItems": MAX_TERMS,
    "items": {"type": "STRING", "maxLength": MAX_SURFACE_LENGTH},
}

ROOM_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "maxItems": MAX_ITEMS,
            "items": {
                "type": "OBJECT",
                "properties": {
                    "category": _SURFACE,
                    "quantity": {
                        "type": "INTEGER",
                        "minimum": 1,
                        "maximum": MAX_QUANTITY,
                    },
                    "colours": _SURFACE_LIST,
                    "materials": _SURFACE_LIST,
                    "max_budget": {"type": "NUMBER", "nullable": True},
                },
                "propertyOrdering": list(RoomItemDraft.model_fields),
            },
        },
        "max_budget": {"type": "NUMBER", "nullable": True},
        "styles": _SURFACE_LIST,
        "preferred_colours": _SURFACE_LIST,
        "room_type": _SURFACE,
        "clarification_question": {
            "type": "STRING",
            "nullable": True,
            "maxLength": MAX_QUESTION_LENGTH,
        },
    },
    "propertyOrdering": list(RoomDraft.model_fields),
}


@dataclass(frozen=True, slots=True)
class Piece:
    """One real product to render, and which reference photo shows it."""

    quantity: int
    category: str
    name: str
    colour: str | None = None
    """The colour the customer will receive, in English."""
    photo: int | None = None
    """1-based position of this product's photo among the references sent,
    or None when no photo could be fetched. Tracked per piece rather than
    assumed from position, because a skipped photo would otherwise shift every
    later piece onto the wrong photograph."""


def image_prompt(
    *,
    pieces: list[Piece],
    room_type: str | None,
    styles: tuple[str, ...],
) -> str:
    """Build the rendering instruction from real catalogue products.

    Two goals pull against each other and both are kept. The room should look
    like something a customer wants to live in: a designer's composition,
    warm light, a palette built around the products, tasteful styling. And the
    furniture must stay exactly the plan: each piece reproduced from its own
    photograph, in the colour the plan chose, in the planned quantity, with no
    extra seating, tables, beds or storage that a customer could mistake for
    part of the purchase. Decor is allowed only because it is small, and the
    disclaimer says it is illustration.
    """

    room = room_type or "living room"
    style = ", ".join(styles) if styles else "warm contemporary"
    lines = [
        f"A beautiful, magazine-quality interior photograph of a {style} {room}, "
        "styled by a professional interior designer. It should feel inviting, "
        "calm and lived-in, the kind of room a person would love to come home to.",
        "",
        "The room contains exactly these pieces of furniture, and every single "
        "one must be clearly and fully visible:",
    ]
    for piece in pieces:
        count = "one" if piece.quantity == 1 else f"exactly {piece.quantity}"
        colour = f", in {piece.colour}" if piece.colour else ""
        if piece.photo is not None:
            source = (
                f"reproduce it from reference photograph {piece.photo} as "
                "faithfully as possible, keeping its shape, fabric and legs"
            )
        else:
            source = "no photograph is available; show a typical one"
        # Stated twice on purpose. Asked for two chairs with the count alone,
        # the model drew one in two renders out of three on 2026-09-18.
        copies = (
            f" Show {piece.quantity} separate, identical copies of this piece, "
            f"every one of the {piece.quantity} fully visible."
            if piece.quantity > 1
            else ""
        )
        lines.append(
            f"- {count} x {piece.category} ({piece.name}){colour}: {source}.{copies}"
        )
    lines += [
        "Count them: the number of each piece in the picture must match this list "
        "exactly. Do not add any other seating, tables, beds or storage.",
        "",
        "Composition: arrange the pieces the way an interior designer would, "
        "balanced and purposeful. Sofas stand against a wall or float facing the "
        "room; chairs are grouped around the table they belong to or angled "
        "towards the sofa for conversation. Everything is to scale with everything "
        "else and with a spacious, uncluttered room, with clear walking space.",
        "",
        "Styling: a harmonious colour palette built around the furniture's own "
        f"colours, suited to a {style} interior. Soft, warm natural daylight from "
        "a large window with sheer curtains, gentle shadows. Finish the room with "
        "small, tasteful decor only: a textured area rug, a few green plants, "
        "cushions and a throw, a floor or table lamp, framed wall art, and a "
        "couple of books or a vase. Decor must stay small and must never look "
        "like additional furniture.",
        "",
        "Camera: eye level, wide angle, straight verticals, sharp focus, "
        "photorealistic, rich detail and texture, professional interior "
        "photography.",
        "",
        "No people, no text, no logos, no watermarks.",
    ]
    return "\n".join(lines)
