"""Typed authentication models."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class AuthenticatedUser(BaseModel):
    """Minimal trusted identity returned after Supabase verification."""

    model_config = ConfigDict(frozen=True, strict=True)

    user_id: UUID


class AuthenticatedRequestContext(BaseModel):
    """Private verified identity plus a non-serializable bearer credential."""

    model_config = ConfigDict(frozen=True, strict=True)

    user_id: UUID
    access_token: SecretStr = Field(exclude=True, repr=False)


class MeResponse(BaseModel):
    """Public response for the current authenticated user."""

    model_config = ConfigDict(frozen=True, strict=True)

    user_id: UUID
    authenticated: Literal[True]
