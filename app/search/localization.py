"""Answer in the language the customer wrote in.

The rule is simple and deterministic: if the sentence contains Arabic, the
response speaks Arabic. Phase 4C already detects that while building the
query, and the Phase 4B vocabularies already carry an Arabic and an English
label for every term, so nothing here is translated at request time and no
model is involved in producing display text.

A mixed sentence answers in Arabic. The marketplace is Egyptian, so a customer
writing "عايز modern dining table" is an Arabic speaker reaching for an English
product word, not an English speaker.

What is not localized, and why. Product names, descriptions, and seller names
are catalogue facts and are shown exactly as the seller wrote them; translating
them would be inventing marketplace data. Style and room-type tokens stay in
English because they are matching keys against enrichment attributes, not
display labels.
"""

from __future__ import annotations

from typing import Literal

from app.catalog.normalization import Vocabulary
from app.search.models import Language

MessageCode = Literal[
    "search_unavailable",
    "search_upstream_error",
    "query_empty",
    "query_too_long",
]

MESSAGES: dict[MessageCode, dict[Literal["ar", "en"], str]] = {
    "search_unavailable": {
        "en": "Search is temporarily unavailable.",
        "ar": "البحث غير متاح مؤقتًا. برجاء المحاولة بعد قليل.",
    },
    "search_upstream_error": {
        "en": "The search request could not be understood.",
        "ar": "تعذّر فهم طلب البحث. برجاء إعادة صياغته.",
    },
    "query_empty": {
        "en": "A search query cannot be empty.",
        "ar": "لا يمكن أن يكون نص البحث فارغًا.",
    },
    "query_too_long": {
        "en": "A search query is too long.",
        "ar": "نص البحث طويل جدًا.",
    },
}


def response_language(language: Language) -> Literal["ar", "en"]:
    """Collapse the detected language to the one the response will speak."""

    return "ar" if language in ("ar", "mixed") else "en"


def message(code: MessageCode, language: Language) -> str:
    """Return a user-facing message in the customer's language."""

    return MESSAGES[code][response_language(language)]


def term_label(vocabulary: Vocabulary, slug: str, language: Language) -> str:
    """Return a vocabulary term's display label in the customer's language.

    Falls back to the other language rather than to the slug, because a term
    with an empty label on one side should still read as a word.
    """

    term = vocabulary.term(slug)
    if response_language(language) == "ar":
        return term.arabic or term.english
    return term.english or term.arabic
