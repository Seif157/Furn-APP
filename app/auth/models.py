"""Typed authentication models."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuthenticatedUser(BaseModel):
    """Minimal trusted identity returned after Supabase verification."""

    model_config = ConfigDict(frozen=True, strict=True)

    user_id: UUID


class MeResponse(BaseModel):
    """Public response for the current authenticated user."""

    model_config = ConfigDict(frozen=True, strict=True)

    user_id: UUID
    authenticated: Literal[True]
