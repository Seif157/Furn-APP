"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, status
from pydantic import BaseModel, ConfigDict

from app.auth.gateway import SupabaseAuthGateway
from app.config import load_settings
from app.routers.users import router as users_router


class HealthResponse(BaseModel):
    """Strict response schema for the service health check."""

    model_config = ConfigDict(strict=True)

    status: Literal["ok"]
    service: Literal["furniture-ai-api"]
    version: Literal["0.1.0"]


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create and close the shared authentication HTTP client."""

    settings = load_settings()
    async with httpx.AsyncClient() as client:
        application.state.auth_gateway = SupabaseAuthGateway(
            client=client,
            settings=settings,
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
