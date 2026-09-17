"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, status
from pydantic import BaseModel, ConfigDict

from app.ai.providers.gemini import build_gemini_provider
from app.auth.gateway import SupabaseAuthGateway
from app.catalog.gateway import SupabaseCatalogueGateway
from app.catalog.router import router as catalogue_router
from app.config import load_ai_settings, load_settings
from app.routers.users import router as users_router
from app.search.router import router as search_router


class HealthResponse(BaseModel):
    """Strict response schema for the service health check."""

    model_config = ConfigDict(strict=True)

    status: Literal["ok"]
    service: Literal["furniture-ai-api"]
    version: Literal["0.1.0"]


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create and close the shared outbound Supabase HTTP client."""

    settings = load_settings()
    # Absent AI configuration is supported and leaves the provider unset, so
    # only the search route refuses. Malformed AI configuration still raises,
    # because a typo in a key should be loud rather than silently disabling a
    # feature.
    ai_settings = load_ai_settings()
    async with httpx.AsyncClient() as client:
        application.state.auth_gateway = SupabaseAuthGateway(
            client=client,
            settings=settings,
        )
        application.state.catalogue_gateway = SupabaseCatalogueGateway(
            client=client,
            settings=settings,
        )
        application.state.ai_provider = build_gemini_provider(
            client=client,
            settings=ai_settings,
        )
        yield


app = FastAPI(title="Furniture AI API", version="0.1.0", lifespan=lifespan)


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


app.include_router(users_router)
app.include_router(catalogue_router)
app.include_router(search_router)
