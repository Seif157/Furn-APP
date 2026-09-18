"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, status
from pydantic import BaseModel, ConfigDict

from app.ai.providers.gemini import build_gemini_provider
from app.auth.gateway import SupabaseAuthGateway
from app.cart.gateway import SupabaseCartCreator, SupabaseCustomerCartReader
from app.cart.router import router as cart_router
from app.catalog.gateway import SupabaseCatalogueGateway
from app.catalog.router import router as catalogue_router
from app.config import AISettings, load_ai_settings, load_settings
from app.core.cache import AICaches
from app.core.limits import Limit, RateLimiter
from app.core.observability import RequestLogMiddleware, configure_logging
from app.recommendations.router import router as recommendations_router
from app.reviews.gateway import SupabaseReviewGateway
from app.reviews.router import router as reviews_router
from app.rooms.images import ReferenceImageFetcher
from app.rooms.router import router as rooms_router
from app.routers.meta import router as meta_router
from app.routers.users import router as users_router
from app.search.router import router as search_router


class HealthResponse(BaseModel):
    """Strict response schema for the service health check."""

    model_config = ConfigDict(strict=True)

    status: Literal["ok"]
    service: Literal["furniture-ai-api"]
    version: Literal["0.1.0"]


def build_rate_limiter(ai_settings: AISettings) -> RateLimiter:
    return RateLimiter(
        {
            "search": Limit(ai_settings.rate_limit_search_per_minute, 60),
            "room_plan": Limit(ai_settings.rate_limit_room_plan_per_minute, 60),
            "room_image": Limit(ai_settings.rate_limit_room_image_per_hour, 3600),
        }
    )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create and close the shared outbound Supabase HTTP client."""

    settings = load_settings()
    # Absent AI configuration is supported and leaves the provider unset, so
    # only the search route refuses. Malformed AI configuration still raises,
    # because a typo in a key should be loud rather than silently disabling a
    # feature.
    ai_settings = load_ai_settings()
    configure_logging(settings.log_level)
    application.state.ai_settings = ai_settings
    # Cost controls for the paid model calls; see app/core/limits.py and
    # app/core/cache.py.
    application.state.rate_limiter = build_rate_limiter(ai_settings)
    application.state.ai_caches = (
        AICaches(ttl_seconds=ai_settings.ai_cache_ttl_seconds)
        if ai_settings.ai_cache_ttl_seconds > 0
        else None
    )
    async with httpx.AsyncClient() as client:
        application.state.auth_gateway = SupabaseAuthGateway(
            client=client,
            settings=settings,
        )
        application.state.catalogue_gateway = SupabaseCatalogueGateway(
            client=client,
            settings=settings,
        )
        application.state.review_gateway = SupabaseReviewGateway(
            client=client,
            settings=settings,
        )
        application.state.cart_reader = SupabaseCustomerCartReader(
            client=client,
            settings=settings,
        )
        # The only place the secret key is used; see app/cart/gateway.py.
        application.state.cart_creator = (
            SupabaseCartCreator(client=client, settings=settings)
            if settings.supabase_secret_key is not None
            else None
        )
        application.state.ai_provider = build_gemini_provider(
            client=client,
            settings=ai_settings,
        )
        # Product photos may be fetched only from the Supabase project itself
        # and the hosts explicitly configured; see ReferenceImageFetcher.
        supabase_host = (settings.supabase_url.host or "").lower()
        application.state.reference_fetcher = ReferenceImageFetcher(
            client=client,
            allowed_hosts=ai_settings.reference_hosts | {supabase_host},
        )
        yield


app = FastAPI(title="Furniture AI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestLogMiddleware)


@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
)
async def get_health() -> HealthResponse:
    """Report that the API process is healthy."""

    return HealthResponse(
        status="ok",
        service="furniture-ai-api",
        version="0.1.0",
    )


app.include_router(meta_router)
app.include_router(users_router)
app.include_router(catalogue_router)
app.include_router(search_router)
app.include_router(rooms_router)
app.include_router(recommendations_router)
app.include_router(reviews_router)
app.include_router(cart_router)
