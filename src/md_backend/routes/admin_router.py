"""Admin router for user management endpoints."""

import logging
import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import UpdateStatusRequest
from md_backend.services.admin_service import AdminService
from md_backend.utils.database import get_db_session
from md_backend.utils.logger import get_logger
from md_backend.utils.security import get_current_superadmin

logger = get_logger(__name__)
_logger_extra = {"component.name": "admin_router","component.version": "v1",}

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
    logger.info(
        "Listing users",
        extra={
            _logger_extra,
            "status_filter": user_status,
            "role": role,
        },
    )

    if user_status is not None and user_status not in _ALLOWED_STATUSES:
        logger.warning(
            "Invalid status filter",
            extra={
                _logger_extra,
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
                _logger_extra,
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
            _logger_extra,
            "count": len(users),
        },
    )

    return JSONResponse(content=users, status_code=status.HTTP_200_OK)
