"""Deterministic, search-oriented normalization of catalogue products.

Phase 4B. This module never contacts a database or an AI provider. It takes an
already validated ``UpstreamProduct`` and produces a ``NormalizedProduct`` that
keeps every original value and adds a canonical, bilingual, search-oriented
representation next to it. The public catalogue API is not changed by it; the
search and recommendation phases consume the normalized form.

Vocabulary sources are recorded in docs/phase-4b-catalogue-normalization.md.
Terms found in the Phase 4A audit evidence are the verified core; the rest are
candidate synonyms that a later audit run can confirm or prune.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.catalog.upstream_models import UpstreamEnrichmentAssignment, UpstreamProduct

ARABIC_SCRIPT = re.compile(r"[؀-ۿ]")
LATIN_SCRIPT = re.compile(r"[a-z]")
# Bilingual catalogue labels are written as "Arabic — English" with an em dash;
# en dash, pipe, and slash are accepted as tolerant equivalents.
LABEL_SEPARATOR = re.compile(r"\s*[—–|/]\s*|\s+-\s+")
TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
WHITESPACE = re.compile(r"\s+")
ARABIC_LETTER_FOLDS = str.maketrans(
    {
        "أ": "ا",  # alef with hamza above -> alef
        "إ": "ا",  # alef with hamza below -> alef
        "آ": "ا",  # alef with madda -> alef
        "ٱ": "ا",  # alef wasla -> alef
        "ى": "ي",  # alef maqsura -> yeh
        "ی": "ي",  # farsi yeh -> yeh
        "ک": "ك",  # keheh -> kaf
        "ة": "ه",  # teh marbuta -> heh
        "٫": ".",  # arabic decimal separator
        "٬": "",  # arabic thousands separator
    }
)
DIGIT_FOLDS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)
NUMBER = r"(?P<value>\d+(?:[.,]\d+)?)"
LENGTH_UNITS: tuple[tuple[str, Decimal], ...] = (
    (r"mm|مم|millimet(?:er|re)s?", Decimal("0.1")),
    (r"cm|سم|centimet(?:er|re)s?", Decimal("1")),
    (r"m|متر|م|met(?:er|re)s?", Decimal("100")),
    (r"in|inch(?:es)?|\"|بوصة", Decimal("2.54")),
)
WEIGHT_UNITS: tuple[tuple[str, Decimal], ...] = (
    (
        r"kg|kgs|كجم|كيلو|kilo(?:gram)?s?",
        Decimal("1"),
    ),
    (r"g|جم|جرام|grams?", Decimal("0.001")),
    (r"lb|lbs|pounds?", Decimal("0.45359237")),
)
CENTIMETRE = Decimal("0.01")


def normalize_text(text: str) -> str:
    """Casefold, fold Arabic letter variants and digits, strip diacritics."""

    folded = unicodedata.normalize("NFKC", text)
    folded = folded.translate(DIGIT_FOLDS).translate(ARABIC_LETTER_FOLDS)
    folded = TASHKEEL.sub("", folded)
    folded = folded.casefold()
    return WHITESPACE.sub(" ", folded).strip()


def has_arabic(text: str) -> bool:
    return ARABIC_SCRIPT.search(text) is not None


def has_latin(text: str) -> bool:
    return LATIN_SCRIPT.search(text.casefold()) is not None


def split_bilingual_label(label: str) -> tuple[str | None, str | None]:
    """Return (arabic, english) halves of a bilingual label, by script."""

    arabic: str | None = None
    english: str | None = None
    for part in (piece.strip() for piece in LABEL_SEPARATOR.split(label)):
        if not part:
            continue
        if has_arabic(part):
            arabic = part if arabic is None else f"{arabic} {part}"
        elif has_latin(part):
            english = part if english is None else f"{english} {part}"
    if arabic is None and english is None and label.strip():
        english = label.strip()
    return arabic, english


def _parse_quantity(
    text: str, units: tuple[tuple[str, Decimal], ...]
) -> Decimal | None:
    normalized = normalize_text(text)
    for unit_pattern, factor in units:
        match = re.search(
            rf"(?<![\d.]){NUMBER}\s*(?:{unit_pattern})(?![a-z؀-ۿ])",
            normalized,
        )
        if match is None:
            continue
        try:
            value = Decimal(match.group("value").replace(",", "."))
        except InvalidOperation:
            return None
        if value <= 0:
            return None
        return (value * factor).quantize(CENTIMETRE, rounding=ROUND_HALF_UP)
    return None


def parse_length_cm(text: str) -> Decimal | None:
    """Parse "220 cm", "2.2 m", "2200mm", "٢٢٠ سم", or "86.6 in" to centimetres."""

    return _parse_quantity(text, LENGTH_UNITS)


def parse_weight_kg(text: str) -> Decimal | None:
    """Parse "12.5 kg", "12500 g", "٢٠ كجم", or "27 lb" to kilograms."""

    return _parse_quantity(text, WEIGHT_UNITS)


@dataclass(frozen=True, slots=True)
class VocabularyTerm:
    slug: str
    english: str
    arabic: str
    synonyms: tuple[str, ...] = ()
    verified: bool = False
    """True when the term appears in the Phase 4A audit evidence."""


class Vocabulary:
    """A controlled bilingual vocabulary with normalized synonym lookup."""

    def __init__(self, name: str, terms: tuple[VocabularyTerm, ...]) -> None:
        self.name = name
        self.terms = terms
        self._index: dict[str, VocabularyTerm] = {}
        for term in terms:
            for surface in (term.english, term.arabic, *term.synonyms):
                key = normalize_text(surface)
                existing = self._index.get(key)
                if existing is not None and existing is not term:
                    raise ValueError(f"{name}: ambiguous synonym {surface!r}")
                self._index[key] = term
        self._by_slug = {term.slug: term for term in terms}
        if len(self._by_slug) != len(terms):
            raise ValueError(f"{name}: duplicate slug")

    def lookup(self, surface: str) -> VocabularyTerm | None:
        """Resolve a surface form, a bilingual label, or either half of one."""

        direct = self._index.get(normalize_text(surface))
        if direct is not None:
            return direct
        arabic, english = split_bilingual_label(surface)
        candidates = {
            self._index.get(normalize_text(half))
            for half in (arabic, english)
            if half is not None
        } - {None}
        if len(candidates) == 1:
            return candidates.pop()
        return None

    def term(self, slug: str) -> VocabularyTerm:
        return self._by_slug[slug]


CATEGORIES = Vocabulary(
    "category",
    (
        # Multi-word phrasings are listed explicitly because lookup matches a
        # whole surface, not its tokens. A customer asking for "كرسي مكتب"
        # said the right thing; without the entry the category simply does not
        # resolve and the search widens to everything.
        VocabularyTerm(
            "beds",
            "Beds",
            "أسرّة",
            ("bed", "سرير", "اسرة", "سرير نوم", "beds frame", "bed frame"),
            True,
        ),
        VocabularyTerm(
            "dining",
            "Dining",
            "سفرة",
            (
                "dining table",
                "طاولة سفرة",
                "dining set",
                "ترابيزة سفرة",
                "طاولة طعام",
                "dining room table",
                # A bare "table" resolves here because dining tables are the
                # only tables this catalogue sells. "coffee table" is a
                # different whole surface and stays unresolved, since that is
                # a table the catalogue does not carry.
                "table",
                "طاولة",
                "ترابيزة",
                "تربيزة",
            ),
            True,
        ),
        VocabularyTerm(
            "sofas",
            "Sofas",
            "كنب",
            ("sofa", "couch", "كنبة", "أريكة", "كنبة سرير", "sofa bed", "settee"),
            True,
        ),
        VocabularyTerm(
            "wardrobes",
            "Wardrobes",
            "دواليب",
            ("wardrobe", "closet", "دولاب", "دولاب ملابس", "خزانة ملابس", "خزانة"),
            True,
        ),
        VocabularyTerm(
            "chairs",
            "Chairs",
            "كراسي",
            ("chair", "كرسي", "كرسي مكتب", "office chair", "desk chair", "كرسي سفرة"),
            True,
        ),
    ),
)

COLOURS = Vocabulary(
    "colour",
    (
        VocabularyTerm("white", "white", "أبيض", (), True),
        VocabularyTerm("brown", "brown", "بني", (), True),
        VocabularyTerm("dark_brown", "dark brown", "بني غامق", ("dark-brown",), True),
        VocabularyTerm("beige", "beige", "بيج", (), True),
        VocabularyTerm("grey", "grey", "رمادي", ("gray",), True),
        VocabularyTerm("natural", "natural", "طبيعي", (), True),
        VocabularyTerm("navy", "navy", "كحلي", ("navy blue",), True),
        VocabularyTerm("wenge", "wenge", "وينجيه", ("وينجه",), True),
        VocabularyTerm("black", "black", "أسود", ()),
        VocabularyTerm("red", "red", "أحمر", ()),
        VocabularyTerm("blue", "blue", "أزرق", ()),
        VocabularyTerm("green", "green", "أخضر", ()),
        VocabularyTerm("yellow", "yellow", "أصفر", ()),
        VocabularyTerm("cream", "cream", "كريمي", ("off white", "off-white")),
        VocabularyTerm("walnut", "walnut", "جوزي", ()),
        VocabularyTerm("oak", "oak", "بلوطي", ()),
    ),
)

MATERIALS = Vocabulary(
    "material",
    (
        VocabularyTerm("beech_wood", "beech wood", "خشب زان", ("beech", "zan"), True),
        VocabularyTerm(
            "wood", "wood", "خشب", ("wooden", "solid wood", "خشب طبيعي"), True
        ),
        VocabularyTerm("cotton", "cotton", "قطن", (), True),
        VocabularyTerm(
            "fabric", "fabric", "قماش", ("textile", "upholstery fabric"), True
        ),
        VocabularyTerm("mdf", "mdf", "إم دي إف", ("m.d.f",), True),
        VocabularyTerm("oak", "oak", "بلوط", ("خشب بلوط",)),
        VocabularyTerm("linen", "linen", "كتان", ()),
        VocabularyTerm("velvet", "velvet", "قطيفة", ()),
        VocabularyTerm("leather", "leather", "جلد", ("جلد طبيعي",)),
        VocabularyTerm("metal", "metal", "معدن", ("iron", "حديد")),
        VocabularyTerm("steel", "steel", "ستانلس", ("stainless steel", "ستانلس ستيل")),
        VocabularyTerm("glass", "glass", "زجاج", ()),
        VocabularyTerm("marble", "marble", "رخام", ()),
        VocabularyTerm("plywood", "plywood", "أبلكاش", ()),
        VocabularyTerm("foam", "foam", "إسفنج", ()),
        VocabularyTerm("rattan", "rattan", "خيزران", ()),
        VocabularyTerm("walnut", "walnut", "جوز", ("خشب جوز",)),
    ),
)


# Styles, room types and feels describe how a product looks and where it goes.
# No seller types them in, so they are inferred by the platform and kept apart
# from seller facts (app/catalog/tags.py). The vocabulary exists so that the
# customer's word and the inferred tag land on the same slug: without it
# "مودرن" and "modern" are two unrelated strings and the match never happens.
STYLES = Vocabulary(
    "style",
    (
        VocabularyTerm(
            "modern",
            "modern",
            "مودرن",
            ("contemporary", "عصري", "حديث", "modern style"),
        ),
        VocabularyTerm(
            "classic",
            "classic",
            "كلاسيك",
            ("classical", "كلاسيكي", "traditional", "تقليدي"),
        ),
        VocabularyTerm(
            "neoclassic",
            "neoclassic",
            "نيوكلاسيك",
            ("neo classic", "neo-classic", "neoclassical"),
        ),
        VocabularyTerm(
            "scandinavian",
            "scandinavian",
            "إسكندنافي",
            ("scandi", "nordic", "اسكندنافي", "سكندنافي"),
        ),
        VocabularyTerm(
            "minimal",
            "minimal",
            "بسيط",
            ("minimalist", "simple", "مينيمال", "بساطة"),
        ),
        VocabularyTerm(
            "industrial",
            "industrial",
            "إندستريال",
            ("loft", "اندستريال", "صناعي"),
        ),
        VocabularyTerm(
            "rustic",
            "rustic",
            "ريفي",
            ("farmhouse", "country", "كانتري"),
        ),
        VocabularyTerm(
            "boho",
            "boho",
            "بوهيمي",
            ("bohemian", "بوهو"),
        ),
        VocabularyTerm(
            "oriental",
            "oriental",
            "شرقي",
            ("arabesque", "أرابيسك", "ارابيسك", "eastern"),
        ),
        VocabularyTerm(
            "art_deco",
            "art deco",
            "آرت ديكو",
            ("art-deco", "artdeco", "ارت ديكو"),
        ),
    ),
)

ROOM_TYPES = Vocabulary(
    "room type",
    (
        # Egyptians say أوضة, not غرفة, and say it in the plural when they
        # mean several. Measured on 2026-09-20: "٣ أوض نوم" resolved to nothing
        # at all, so a three-bedroom flat became a brief with no bedrooms.
        VocabularyTerm(
            "living_room",
            "living room",
            "غرفة معيشة",
            (
                "living",
                "lounge",
                "ليفنج",
                "معيشة",
                "صالة",
                "living-room",
                "أوضة معيشة",
                "أوض معيشة",
                "غرف معيشة",
                "أوضة قعاد",
            ),
        ),
        # Egypt sells the formal sitting room as a reception, and the entrance
        # set as an antrée. Both are the room a customer names out loud.
        VocabularyTerm(
            "reception",
            "reception",
            "ريسبشن",
            ("انتريه", "أنتريه", "antre", "formal living room", "استقبال"),
        ),
        VocabularyTerm(
            "bedroom",
            "bedroom",
            "غرفة نوم",
            (
                "bed room",
                "نوم",
                "master bedroom",
                "غرفة النوم",
                "غرف نوم",
                "أوضة نوم",
                "أوض نوم",
                "اوضه نوم",
                "غرفة نوم رئيسية",
            ),
        ),
        VocabularyTerm(
            "kids_room",
            "kids room",
            "غرفة أطفال",
            (
                "children room",
                "nursery",
                "أطفال",
                "اطفال",
                "kids",
                "غرف أطفال",
                "أوضة أطفال",
                "أوض أطفال",
                "غرفة الأطفال",
            ),
        ),
        VocabularyTerm(
            "dining_room",
            "dining room",
            "غرفة سفرة",
            (
                "dining",
                "سفرة",
                "غرفة طعام",
                "dining-room",
                "أوضة سفرة",
                "أوض سفرة",
                "غرف سفرة",
            ),
        ),
        VocabularyTerm(
            "home_office",
            "home office",
            "مكتب منزلي",
            (
                "office",
                "مكتب",
                "study",
                "دراسة",
                "work from home",
                "أوضة مكتب",
                "غرفة مكتب",
            ),
        ),
        VocabularyTerm(
            "guest_room",
            "guest room",
            "غرفة ضيوف",
            (
                "guests",
                "ضيوف",
                "spare room",
                "غرف ضيوف",
                "أوضة ضيوف",
                "أوض ضيوف",
            ),
        ),
        VocabularyTerm(
            "balcony",
            "balcony",
            "بلكونة",
            ("terrace", "تراس", "outdoor", "خارجي", "شرفة"),
        ),
        VocabularyTerm(
            "hallway",
            "hallway",
            "مدخل",
            ("entrance", "corridor", "ممر"),
        ),
    ),
)

# A feel is what the customer wants the room to be like, not what the product
# is made of. It is the fuzzy half of search: nothing in the catalogue answers
# "cosy", so it can only ever rank, never filter.
FEELS = Vocabulary(
    "feel",
    (
        VocabularyTerm(
            "cosy",
            "cosy",
            "دافئ ومريح",
            ("cozy", "snug", "مريح", "دافي", "كوزي"),
        ),
        VocabularyTerm(
            "luxury",
            "luxurious",
            "فخم",
            ("luxury", "premium", "فاخر", "لوكس", "high end", "راقي"),
        ),
        VocabularyTerm(
            "warm",
            "warm",
            "دافئ",
            ("warm tones", "ألوان دافئة", "دافيء"),
        ),
        VocabularyTerm(
            "airy",
            "airy",
            "واسع ومضيء",
            ("bright", "light", "مضيء", "منور", "spacious feel"),
        ),
        VocabularyTerm(
            "calm",
            "calm",
            "هادئ",
            ("serene", "relaxing", "مريح للأعصاب", "هادي"),
        ),
        VocabularyTerm(
            "hotel_like",
            "hotel-like",
            "زي الفنادق",
            ("hotel", "hotel style", "فندقي", "زي الفندق"),
        ),
        VocabularyTerm(
            "family_friendly",
            "family friendly",
            "مناسب للعيلة",
            ("kid friendly", "للأطفال", "عملي للعيلة", "practical for family"),
        ),
        VocabularyTerm(
            "space_saving",
            "space saving",
            "موفر للمساحة",
            ("compact", "small space", "مساحة صغيرة", "صغير الحجم", "يوفر مساحة"),
        ),
        VocabularyTerm(
            "statement",
            "statement",
            "لافت",
            ("bold", "eye catching", "جريء", "مميز"),
        ),
    ),
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TextField(FrozenModel):
    original: str
    normalized: str
    has_arabic: bool
    has_latin: bool


class Term(FrozenModel):
    """An original surface form with its canonical vocabulary mapping, if any."""

    original: str
    normalized: str
    slug: str | None
    label_en: str | None
    label_ar: str | None
    verified: bool


class NormalizedCategory(Term):
    id: UUID


class NormalizedColour(Term):
    id: UUID
    stock_quantity: int


class NormalizedAttribute(FrozenModel):
    kind: str
    value_original: str
    value_normalized: str


TagKind = Literal["style", "room_type", "feel"]

TAG_VOCABULARIES: dict[str, Vocabulary] = {
    "style": STYLES,
    "room_type": ROOM_TYPES,
    "feel": FEELS,
}

MAX_TAG_CONFIDENCE = Decimal("1")


class InferredTag(FrozenModel):
    """A platform guess about how a product looks, reads, or feels.

    It is not a seller fact and is never shown as one. No seller types a style
    in, so the alternative is not better data, it is none: without these tags
    "cosy" and "hotel-like" cannot rank anything at all. The confidence travels
    with the tag so ranking can prefer a sure guess to a shaky one, and so a
    guess can never outweigh something the seller actually stated.
    """

    kind: TagKind
    slug: str
    confidence: Decimal

    @field_validator("confidence")
    @classmethod
    def _bounded(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > MAX_TAG_CONFIDENCE:
            raise ValueError("confidence must be within (0, 1]")
        return value

    @model_validator(mode="after")
    def _known_slug(self) -> InferredTag:
        vocabulary = TAG_VOCABULARIES[self.kind]
        try:
            vocabulary.term(self.slug)
        except KeyError:
            raise ValueError(f"unknown {self.kind} slug") from None
        return self


class NormalizedProduct(FrozenModel):
    id: UUID
    name: TextField
    description: TextField | None
    category: NormalizedCategory
    colours: tuple[NormalizedColour, ...]
    materials: tuple[Term, ...]
    width_cm: Decimal | None
    height_cm: Decimal | None
    depth_cm: Decimal | None
    weight_kg: Decimal | None
    price: Decimal
    discount_price: Decimal | None
    effective_price: Decimal
    attributes: tuple[NormalizedAttribute, ...]
    tags: tuple[InferredTag, ...] = ()
    """Inferred, never stated. Empty until the tag table is populated."""
    search_terms: tuple[str, ...]
    unmapped_terms: tuple[str, ...]
    schema_version: Literal[1]


def _text_field(text: str) -> TextField:
    return TextField(
        original=text,
        normalized=normalize_text(text),
        has_arabic=has_arabic(text),
        has_latin=has_latin(text),
    )


def _term(surface: str, vocabulary: Vocabulary) -> Term:
    matched = vocabulary.lookup(surface)
    return Term(
        original=surface,
        normalized=normalize_text(surface),
        slug=matched.slug if matched else None,
        label_en=matched.english if matched else None,
        label_ar=matched.arabic if matched else None,
        verified=matched.verified if matched else False,
    )


def _attribute_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _confirmed(assignment: UpstreamEnrichmentAssignment) -> bool:
    return assignment.confirmation_state == "party_confirmed"


def normalize_product(product: UpstreamProduct) -> NormalizedProduct:
    """Build the search-oriented representation; pure and deterministic."""

    category_term = _term(product.category.name, CATEGORIES)
    category = NormalizedCategory(id=product.category.id, **category_term.model_dump())
    colours = tuple(
        NormalizedColour(
            id=colour.id,
            stock_quantity=colour.stock_quantity,
            **_term(colour.color_value, COLOURS).model_dump(),
        )
        for colour in sorted(product.colors, key=lambda c: (c.display_order, c.id.int))
    )
    materials = tuple(_term(material, MATERIALS) for material in product.materials)
    attributes = tuple(
        sorted(
            (
                NormalizedAttribute(
                    kind=normalize_text(assignment.attribute.kind),
                    value_original=_attribute_value(assignment.attribute.value),
                    value_normalized=normalize_text(
                        _attribute_value(assignment.attribute.value)
                    ),
                )
                for assignment in product.enrichment_assignments
                if _confirmed(assignment)
            ),
            key=lambda attribute: (attribute.kind, attribute.value_normalized),
        )
    )
    effective_price = (
        product.discount_price
        if product.discount_price is not None and product.discount_price < product.price
        else product.price
    )

    terms: set[str] = set()
    unmapped: set[str] = set()
    for term in (category_term, *colours, *materials):
        if term.slug is not None:
            terms.add(term.slug)
            terms.add(normalize_text(term.label_en or ""))
            terms.add(normalize_text(term.label_ar or ""))
        else:
            unmapped.add(term.normalized)
        terms.add(term.normalized)
    for attribute in attributes:
        terms.add(f"{attribute.kind}:{attribute.value_normalized}")
    terms.discard("")

    return NormalizedProduct(
        id=product.id,
        name=_text_field(product.name),
        description=_text_field(product.description) if product.description else None,
        category=category,
        colours=colours,
        materials=materials,
        width_cm=product.width,
        height_cm=product.height,
        depth_cm=product.depth,
        weight_kg=product.weight,
        price=product.price,
        discount_price=product.discount_price,
        effective_price=effective_price,
        attributes=attributes,
        search_terms=tuple(sorted(terms)),
        unmapped_terms=tuple(sorted(unmapped)),
        schema_version=1,
    )


def with_tags(
    product: NormalizedProduct, tags: tuple[InferredTag, ...]
) -> NormalizedProduct:
    """Attach inferred tags to a normalized product, deterministically ordered."""

    ordered = tuple(sorted(tags, key=lambda tag: (tag.kind, tag.slug, -tag.confidence)))
    deduplicated: dict[tuple[str, str], InferredTag] = {}
    for tag in ordered:
        deduplicated.setdefault((tag.kind, tag.slug), tag)
    return product.model_copy(update={"tags": tuple(deduplicated.values())})
