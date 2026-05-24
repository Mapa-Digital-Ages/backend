"""Admin router for user management endpoints."""

import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import UpdateStatusRequest
from md_backend.routes.content_router import content_router
from md_backend.routes.subject_router import subject_router
from md_backend.routes.upload_router import admin_upload_router
from md_backend.services.admin_service import AdminService
from md_backend.utils.database import get_db_session
from md_backend.utils.logger import get_logger
from md_backend.utils.security import get_current_superadmin

logger = get_logger(__name__)

_logger_extra = {
    "component.name": "admin_router",
    "component.version": "v1",
}

admin_service = AdminService()

admin_router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(get_current_superadmin)],
)

_ALLOWED_STATUSES = {"waiting", "approved", "rejected"}
_ALLOWED_ROLES = {"student", "admin", "guardian"}


@admin_router.get("/users")
async def list_users(
    session: AsyncSession = Depends(get_db_session),
    user_status: str | None = None,
    role: str | None = None,
):
    """List all users, optionally filtered by status."""

    logger.info(
        "Listing users",
        extra={
            **_logger_extra,
            "status_filter": user_status,
            "role": role,
        },
    )

    if user_status is not None and user_status not in _ALLOWED_STATUSES:
        logger.warning(
            "Invalid status filter",
            extra={
                **_logger_extra,
                "status_filter": user_status,
            },
        )

        return JSONResponse(
            content={"detail": "Invalid status."},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if role is not None and role not in _ALLOWED_ROLES:
        logger.warning(
            "Invalid role filter",
            extra={
                **_logger_extra,
                "role": role,
            },
        )

        return JSONResponse(
            content={"detail": "Invalid role."},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    users = await admin_service.list_users(
        session=session,
        status_filter=user_status,
        role=role,
    )

    logger.info(
        "Users listed successfully",
        extra={
            **_logger_extra,
            "count": len(users),
        },
    )

    return JSONResponse(
        content=users,
        status_code=status.HTTP_200_OK,
    )


@admin_router.patch("/users/{user_id}/status")
async def update_user_status(
    user_id: uuid.UUID,
    request: UpdateStatusRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Update a user's approval status."""

    result = await admin_service.update_user_status(
        session=session,
        user_id=user_id,
        new_status=request.status,
    )

    return JSONResponse(
        content=result,
        status_code=status.HTTP_200_OK,
    )


admin_router.include_router(subject_router)
admin_router.include_router(content_router, prefix="/content")
admin_router.include_router(admin_upload_router, prefix="/uploads")