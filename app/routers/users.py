"""Routes for the current authenticated user."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.auth.models import AuthenticatedUser, MeResponse

router = APIRouter(prefix="/v1", tags=["users"])


@router.get("/me", response_model=MeResponse)
async def get_me(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> MeResponse:
    """Return the identity established by the verified access token."""

    return MeResponse(user_id=current_user.user_id, authenticated=True)
