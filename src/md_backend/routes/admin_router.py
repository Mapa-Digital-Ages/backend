"""Admin router for user management endpoints."""

import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import UpdateStatusRequest
from md_backend.services.admin_service import AdminService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_superadmin

admin_service = AdminService()
admin_router = APIRouter(prefix="/admin")

_ALLOWED_STATUSES = {"waiting", "approved", "rejected"}
_ALLOWED_ROLES = {"student", "admin", "guardian"}


@admin_router.get("/users", dependencies=[Depends(get_current_superadmin)])
async def list_users(
    session: AsyncSession = Depends(get_db_session),
    user_status: str | None = None,
    role: str | None = None,
):
    """List all users, optionally filtered by status."""
    if user_status is not None and user_status not in _ALLOWED_STATUSES:
        return JSONResponse(
            content={"detail": "Invalid status."},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if role is not None and role not in _ALLOWED_ROLES:
        return JSONResponse(
            content={"detail": "Invalid role."},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    users = await admin_service.list_users(session=session, status_filter=user_status, role=role)
    return JSONResponse(content=users, status_code=status.HTTP_200_OK)


@admin_router.patch("/users/{user_id}/status", dependencies=[Depends(get_current_superadmin)])
async def update_user_status(
    user_id: uuid.UUID,
    request: UpdateStatusRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Update a user's approval status."""
    result = await admin_service.update_user_status(
        session=session, user_id=user_id, new_status=request.status
    )

    if result is None:
        return JSONResponse(
            content={"detail": "User not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if "error" in result:
        return JSONResponse(
            content={"detail": result["error"]},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)
