"""What the app needs before its first real request.

GET /v1/meta               which features this server has switched on, and limits
GET /v1/search/vocabulary  the words search understands, with both labels
GET /v1/search/examples    sentences to show on empty search and room screens

None of these needs a sign-in or reads the database. They describe the server,
not any customer, so the app can ask before the user logs in and shape its
screens: hide the room preview button when no image model is configured,
build filter chips from the same vocabulary search resolves words to, and
show example sentences that are known to parse well.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request

from app.ai.service import MAX_HISTORY
from app.catalog.models import StrictResponseModel
from app.catalog.normalization import CATEGORIES, COLOURS, MATERIALS, Vocabulary
from app.config import AISettings
from app.recommendations.comparison import MAX_COMPARED
from app.recommendations.similar import MAX_SIMILAR
from app.rooms.models import MAX_ITEMS, MAX_QUANTITY
from app.search.models import MAX_RESULTS, MAX_TEXT_LENGTH

API_VERSION = "0.1.0"

router = APIRouter(prefix="/v1", tags=["meta"])


class FeaturesResponse(StrictResponseModel):
    search: bool
    """Natural-language search, including refinement with `history`."""
    room_planning: bool
    room_preview: bool
    compare: bool
    similar_products: bool
    public_reviews: bool


class LimitsResponse(StrictResponseModel):
    search_per_minute: int
    room_plan_per_minute: int
    room_preview_per_hour: int
    max_query_length: int
    max_history: int
    max_search_results: int
    max_room_pieces: int
    max_piece_quantity: int
    max_compared_products: int
    max_similar_products: int


class MetaResponse(StrictResponseModel):
    api_version: str
    languages: tuple[Literal["ar", "en"], ...]
    features: FeaturesResponse
    limits: LimitsResponse


class TermResponse(StrictResponseModel):
    slug: str
    en: str
    ar: str


class VocabularyResponse(StrictResponseModel):
    categories: tuple[TermResponse, ...]
    colours: tuple[TermResponse, ...]
    materials: tuple[TermResponse, ...]


class ExamplesResponse(StrictResponseModel):
    search: tuple[str, ...]
    search_refinements: tuple[str, ...]
    rooms: tuple[str, ...]
    room_refinements: tuple[str, ...]


# Every sentence here was run against the live model and the seed catalogue on
# 2026-09-17/18 and parsed as intended; see docs/phase-5d-search-evaluation.md
# and docs/phase-8-room-planning.md. Keep it that way: an example that fails
# on stage is worse than no example.
EXAMPLES: dict[str, ExamplesResponse] = {
    "ar": ExamplesResponse(
        search=(
            "عايز كنبة مودرن بيج أقل من ٣٠ ألف",
            "محتاج سرير خشب زان بحد أقصى ١٢ ألف",
            "عايز كنبة مش أوسع من ٢٠٠ سم",
            "محتاج دولاب أبيض",
        ),
        search_refinements=("خليها رمادي", "في حدود ١٥ ألف"),
        rooms=(
            "عايز أوضة معيشة مودرن فيها كنبة و2 كرسي وترابيزة في حدود 40 ألف",
            "عايز أوضة معيشة مودرن فيها كنبة في حدود 12 ألف و2 كرسي وترابيزة، "
            "والميزانية كلها 25 ألف",
        ),
        room_refinements=("خلي الكراسي 4", "زود الميزانية لـ 50 ألف"),
    ),
    "en": ExamplesResponse(
        search=(
            "I need a modern beige sofa under 30,000 EGP",
            "a beech wood bed under 20000",
            "a sofa no wider than 200 cm",
            "a white wardrobe under 12000",
        ),
        search_refinements=("actually keep it under 15000", "cheaper"),
        rooms=(
            "a scandinavian living room with a sofa, two chairs and a table "
            "under 30000",
        ),
        room_refinements=("make the chairs 4",),
    ),
}


def _terms(vocabulary: Vocabulary) -> tuple[TermResponse, ...]:
    return tuple(
        TermResponse(slug=term.slug, en=term.english, ar=term.arabic)
        for term in vocabulary.terms
    )


VOCABULARY = VocabularyResponse(
    categories=_terms(CATEGORIES),
    colours=_terms(COLOURS),
    materials=_terms(MATERIALS),
)


@router.get("/meta", response_model=MetaResponse)
async def get_meta(request: Request) -> MetaResponse:
    """Switched-on features and limits. Contains no secret and no customer data."""

    state = request.app.state
    settings: AISettings = getattr(state, "ai_settings", None) or AISettings(
        _env_file=None
    )
    ai_ready = getattr(state, "ai_provider", None) is not None
    return MetaResponse(
        api_version=API_VERSION,
        languages=("ar", "en"),
        features=FeaturesResponse(
            search=ai_ready,
            room_planning=ai_ready,
            room_preview=ai_ready,
            compare=True,
            similar_products=True,
            public_reviews=True,
        ),
        limits=LimitsResponse(
            search_per_minute=settings.rate_limit_search_per_minute,
            room_plan_per_minute=settings.rate_limit_room_plan_per_minute,
            room_preview_per_hour=settings.rate_limit_room_image_per_hour,
            max_query_length=MAX_TEXT_LENGTH,
            max_history=MAX_HISTORY,
            max_search_results=MAX_RESULTS,
            max_room_pieces=MAX_ITEMS,
            max_piece_quantity=MAX_QUANTITY,
            max_compared_products=MAX_COMPARED,
            max_similar_products=MAX_SIMILAR,
        ),
    )


@router.get("/search/vocabulary", response_model=VocabularyResponse)
async def get_vocabulary() -> VocabularyResponse:
    """The categories, colours and materials search resolves words to."""

    return VOCABULARY


@router.get("/search/examples", response_model=ExamplesResponse)
async def get_examples(language: Literal["ar", "en"] = "en") -> ExamplesResponse:
    """Sentences known to work, for empty search and room-planner screens."""

    return EXAMPLES[language]
