"""Room planning endpoints.

POST /v1/rooms/plan   one sentence in, a room of real products within budget
POST /v1/rooms/image  product ids in, a labelled AI preview image out

Two endpoints because they cost different amounts of time. A plan takes a few
seconds and is the part a customer acts on; a preview takes ten to twenty and
is decoration. Keeping them apart means a slow or refused image never delays or
breaks the plan.

Both read the catalogue with the caller's own token through the existing
gateway, so row-level security decides what can be planned or rendered, exactly
as it does for search.
"""

from __future__ import annotations

import base64
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.ai.provider import (
    AIProvider,
    AIProviderError,
    AIProviderUnavailableError,
    ImageBytes,
)
from app.ai.service import InvalidQueryError
from app.auth.dependencies import get_authenticated_request
from app.auth.models import AuthenticatedRequestContext
from app.catalog.dependencies import (
    catalogue_service_unavailable,
    catalogue_upstream_error,
    get_catalogue_gateway,
    product_not_found,
)
from app.catalog.gateway import (
    CatalogueGateway,
    CatalogueServiceUnavailableError,
    CatalogueUpstreamError,
)
from app.catalog.normalization import CATEGORIES, COLOURS, normalize_product
from app.catalog.transform import build_product_response, is_recommendation_eligible
from app.rooms.images import ReferenceImageFetcher
from app.rooms.parser import parse_room_request
from app.rooms.planner import plan_room
from app.rooms.prompts import Piece, image_prompt
from app.rooms.responses import (
    PREVIEW_DISCLAIMER,
    PREVIEW_LABEL,
    RoomImageItem,
    RoomImageRequest,
    RoomImageResponse,
    RoomPlanResponse,
    build_room_plan_response,
)
from app.search.dependencies import (
    get_optional_ai_provider,
    invalid_search_query,
    search_unavailable,
    search_upstream_error,
)
from app.search.models import MAX_TEXT_LENGTH, detect_language
from app.search.router import CANDIDATE_LIMIT

router = APIRouter(prefix="/v1/rooms", tags=["rooms"])


class RoomPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: Annotated[str, Field(min_length=1, max_length=MAX_TEXT_LENGTH)]


async def get_reference_fetcher(request: Request) -> ReferenceImageFetcher | None:
    return getattr(request.app.state, "reference_fetcher", None)


def _one_line(text: str) -> str:
    """Collapse client text to a single line before it joins a prompt."""

    return " ".join(text.split())


@router.post("/plan", response_model=RoomPlanResponse)
async def plan(
    plan_request: RoomPlanRequest,
    authenticated_request: Annotated[
        AuthenticatedRequestContext, Depends(get_authenticated_request)
    ],
    gateway: Annotated[CatalogueGateway, Depends(get_catalogue_gateway)],
    provider: Annotated[AIProvider | None, Depends(get_optional_ai_provider)],
) -> RoomPlanResponse:
    """Plan a room of real products from one sentence."""

    language = detect_language(plan_request.query)
    if provider is None:
        raise search_unavailable(language)

    try:
        specification = await parse_room_request(plan_request.query, provider=provider)
    except InvalidQueryError:
        raise invalid_search_query("query_empty", language) from None
    except AIProviderUnavailableError:
        raise search_unavailable(language) from None
    except AIProviderError:
        raise search_upstream_error(language) from None

    try:
        products = await gateway.list_products(
            authenticated_request=authenticated_request,
            limit=CANDIDATE_LIMIT,
            offset=0,
        )
    except CatalogueServiceUnavailableError:
        raise catalogue_service_unavailable() from None
    except CatalogueUpstreamError:
        raise catalogue_upstream_error() from None

    candidates = tuple(
        product
        for product in products[:CANDIDATE_LIMIT]
        if is_recommendation_eligible(product)
    )
    room = plan_room(
        (normalize_product(product) for product in candidates), specification
    )
    return build_room_plan_response(candidates, plan=room, specification=specification)


@router.post("/image", response_model=RoomImageResponse)
async def image(
    image_request: RoomImageRequest,
    authenticated_request: Annotated[
        AuthenticatedRequestContext, Depends(get_authenticated_request)
    ],
    gateway: Annotated[CatalogueGateway, Depends(get_catalogue_gateway)],
    provider: Annotated[AIProvider | None, Depends(get_optional_ai_provider)],
    fetcher: Annotated[ReferenceImageFetcher | None, Depends(get_reference_fetcher)],
) -> RoomImageResponse:
    """Render a labelled preview of real products the caller may see."""

    language = image_request.language
    if provider is None:
        raise search_unavailable(language)

    # The same product listed twice is one piece with a larger quantity, in
    # the first colour asked for.
    quantities: dict = {}
    colours: dict = {}
    for item in image_request.items:
        quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
        colours.setdefault(item.product_id, item.colour_id)

    pieces: list[Piece] = []
    references: list[ImageBytes] = []
    for product_id, quantity in quantities.items():
        try:
            product = await gateway.get_product(
                authenticated_request=authenticated_request, product_id=product_id
            )
        except CatalogueServiceUnavailableError:
            raise catalogue_service_unavailable() from None
        except CatalogueUpstreamError:
            raise catalogue_upstream_error() from None
        # Looked up again rather than trusted from the client: a product the
        # caller cannot see, or one that is not for sale, is never rendered.
        shown = build_product_response(product) if product is not None else None
        if product is None or shown is None:
            raise product_not_found()

        normalized = normalize_product(product)
        slug = normalized.category.slug
        category = CATEGORIES.term(slug).english.lower() if slug else "furniture"

        # Only a colour this product really has counts; anything else sent by
        # the client is ignored rather than described to the model.
        colour_id = colours[product_id]
        colour = next((c for c in normalized.colours if c.id == colour_id), None)
        colour_name = (
            COLOURS.term(colour.slug).english
            if colour is not None and colour.slug
            else (_one_line(colour.original) if colour is not None else None)
        )

        # That colour's own photo when the catalogue has one, else the primary.
        photos = [
            i for i in shown.images if colour is not None and i.color_id == colour.id
        ]
        photos = photos or list(shown.images)
        photo_number: int | None = None
        if fetcher is not None and photos:
            reference = await fetcher.fetch(str(photos[0].url))
            if reference is not None:
                references.append(reference)
                photo_number = len(references)

        pieces.append(
            Piece(
                quantity=quantity,
                category=category,
                name=_one_line(shown.name),
                colour=colour_name,
                photo=photo_number,
            )
        )

    prompt = image_prompt(
        pieces=pieces,
        room_type=_one_line(image_request.room_type)
        if image_request.room_type
        else None,
        styles=tuple(_one_line(s) for s in image_request.styles if s.strip()),
    )
    try:
        generated = await provider.generate_image(prompt=prompt, references=references)
    except AIProviderUnavailableError:
        raise search_unavailable(language) from None
    except AIProviderError:
        raise search_upstream_error(language) from None

    return RoomImageResponse(
        image_base64=base64.b64encode(generated.data).decode("ascii"),
        mime_type=generated.mime_type,
        label=PREVIEW_LABEL[language],
        disclaimer=PREVIEW_DISCLAIMER[language],
        items=tuple(
            RoomImageItem(
                product_id=product_id,
                quantity=quantity,
                colour_id=colours[product_id],
            )
            for product_id, quantity in quantities.items()
        ),
        references_used=len(references),
    )
