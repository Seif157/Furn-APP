"""The requirement-extraction instruction and its response schema.

Both are derived from live code at import time. The vocabulary lists come from
``app.catalog.normalization`` and the schema mirrors ``RequirementDraft``, so a
new colour or a renamed field cannot leave the prompt describing a system that
no longer exists. A test asserts the schema and the draft model still agree.

The instruction is guidance, not enforcement. Everything it asks for is checked
again by deterministic code, because a prompt is the one part of this pipeline
an adversarial sentence can argue with.
"""

from __future__ import annotations

from typing import Any

from app.ai.models import MAX_QUESTION_LENGTH, MAX_SURFACE_LENGTH, RequirementDraft
from app.catalog.normalization import CATEGORIES, COLOURS, MATERIALS, Vocabulary
from app.search.models import MAX_TERMS


def _vocabulary_lines(vocabulary: Vocabulary) -> str:
    return "\n".join(f"  {term.english} / {term.arabic}" for term in vocabulary.terms)


REQUIREMENT_INSTRUCTION = f"""\
You extract furniture shopping requirements from one sentence. You work for a
furniture marketplace in Egypt. Customers write in Arabic, in English, or in a
mix of both.

Return only what the sentence actually says. Omit anything it does not say.
Never guess a budget, a size, a colour, or a material the customer did not
mention. An empty answer is correct for a sentence that states no requirements.

Separate what the customer requires from what the customer merely prefers.

  A requirement is a limit or a demand: "under 30,000", "must be beech wood",
  "no wider than 220 cm", "only if it is in stock". Put it in the required and
  min/max fields.

  A preference is a liking or a leaning: "preferably modern", "I like beige",
  "around 200 cm". Put it in the preferred, styles, room_type, and target
  fields.

"around", "roughly", "about" describe a preference, not a limit. "at most",
"under", "no more than", "maximum", "أقل من", "في حدود ميزانية" describe a
limit.

Colour and material are not treated the same way, because customers do not
treat them the same way.

  A colour the customer simply describes is a preference. "كنبة بيج" and "a
  white wardrobe" both go in preferred_colours. Only an explicit demand makes
  a colour required: "لازم أبيض", "must be white", "white only". Colour is the
  attribute people substitute most, and filtering it away hides products they
  would have bought.

  A material the customer names is a requirement. "خشب زان" and "beech wood"
  go in required_materials. Someone who names a material rarely accepts a
  different one.

Rules for values:

  Express every length in centimetres. Convert metres and inches yourself.
  Express every price as a plain number of Egyptian pounds. Ignore the
  currency word, and read "30k", "٣٠ ألف", and "30,000" all as 30000.
  Never return a negative or zero number. Omit the field instead.
  Return at most {MAX_TERMS} items in any list, and at most
  {MAX_SURFACE_LENGTH} characters in any single word or phrase.
  Set in_stock_only to false only when the customer says they will wait or
  that availability does not matter. Otherwise leave it true.

Use the marketplace's own words when the sentence means one of them. Write
either the English or the Arabic form exactly as listed here.

Categories:
{_vocabulary_lines(CATEGORIES)}

Colours:
{_vocabulary_lines(COLOURS)}

Materials:
{_vocabulary_lines(MATERIALS)}

If the customer names something that is not in these lists, write their own
word. Do not substitute the nearest listed word.

Fill in category with the customer's own word for the thing they asked for.
Copy their word, not the closest entry in the list above: "coffee table" stays
"coffee table" and "مكتب" stays "مكتب". Leave category null only when they
named no kind of furniture at all. Never put a category there that the customer
did not ask for; a wrong category is worse than an empty one.

Styles and room types are free text. Write them in English, lowercase, as the
customer meant them, for example "modern", "scandinavian", "living room".

Set clarification_question only when the sentence is too vague to search at
all, such as "I need furniture". A sentence naming a category is searchable, so
leave the question null even if many details are missing. Ask at most one
question, under {MAX_QUESTION_LENGTH} characters.

Write that question in the customer's own language. If their sentence contains
any Arabic, write the question in Egyptian Arabic. Only if their sentence is
entirely in English do you write it in English. This is the one field the
customer reads word for word, so it must sound like their own language and not
a translation.

You never see the product catalogue and you never name a specific product, a
seller, a price that exists, or a stock level. You only restate what the
customer asked for.
"""


_NUMBER: dict[str, Any] = {"type": "NUMBER", "nullable": True}
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

REQUIREMENT_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "category": _SURFACE,
        "required_colours": _SURFACE_LIST,
        "required_materials": _SURFACE_LIST,
        "min_price": _NUMBER,
        "max_price": _NUMBER,
        "min_width_cm": _NUMBER,
        "max_width_cm": _NUMBER,
        "min_height_cm": _NUMBER,
        "max_height_cm": _NUMBER,
        "min_depth_cm": _NUMBER,
        "max_depth_cm": _NUMBER,
        "in_stock_only": {"type": "BOOLEAN"},
        "preferred_colours": _SURFACE_LIST,
        "preferred_materials": _SURFACE_LIST,
        "styles": _SURFACE_LIST,
        "room_type": _SURFACE,
        "preferred_width_cm": _NUMBER,
        "preferred_height_cm": _NUMBER,
        "preferred_depth_cm": _NUMBER,
        "target_price": _NUMBER,
        "clarification_question": {
            "type": "STRING",
            "nullable": True,
            "maxLength": MAX_QUESTION_LENGTH,
        },
    },
    # Deterministic key order makes two identical requests produce byte-identical
    # output, which is what lets the offline fixtures stay meaningful.
    "propertyOrdering": list(RequirementDraft.model_fields),
}
