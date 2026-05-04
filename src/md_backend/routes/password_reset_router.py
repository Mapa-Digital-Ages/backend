"""Password reset router."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
)
from md_backend.services.password_reset_service import PasswordResetService
from md_backend.utils.database import get_db_session

password_reset_service = PasswordResetService()

password_reset_router = APIRouter(prefix="/password-reset")


@password_reset_router.post("/request", response_model=PasswordResetRequestResponse)
async def request_password_reset(
    request: PasswordResetRequest, session: AsyncSession = Depends(get_db_session)
):
    """Generate a password reset code for the requested email."""
    result = await password_reset_service.request_reset(email=request.email, session=session)
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@password_reset_router.post("/confirm")
async def confirm_password_reset(
    request: PasswordResetConfirmRequest, session: AsyncSession = Depends(get_db_session)
):
    """Confirm a password reset code and update the user password."""
    was_reset = await password_reset_service.confirm_reset(
        email=request.email,
        code=request.code,
        new_password=request.new_password,
        session=session,
    )

    if not was_reset:
        return JSONResponse(
            content={"detail": "Invalid or expired reset code"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return JSONResponse(
        content={"detail": "Password reset completed"},
        status_code=status.HTTP_200_OK,
    )
