"""Password reset router."""

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
)
from md_backend.services.password_reset_service import PasswordResetService
from md_backend.utils.database import get_db_session
from md_backend.utils.limiter import limiter

password_reset_service = PasswordResetService()

password_reset_router = APIRouter(prefix="/password-reset")


@password_reset_router.post("/request", response_model=PasswordResetRequestResponse)
@limiter.limit("5/minute")
async def request_password_reset(
    request: Request,
    body: PasswordResetRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Generate a password reset code for the requested email."""
    result = await password_reset_service.request_reset(email=body.email, session=session)
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@password_reset_router.post("/confirm")
@limiter.limit("5/minute")
async def confirm_password_reset(
    request: Request,
    body: PasswordResetConfirmRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Confirm a password reset code and update the user password."""
    was_reset = await password_reset_service.confirm_reset(
        email=body.email,
        code=body.code,
        new_password=body.new_password,
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
