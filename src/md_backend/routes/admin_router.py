"""Admin router for user management endpoints."""

import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import UpdateStatusRequest
from md_backend.routes.admin_resource_router import admin_resource_router
from md_backend.models.api_models import (
    PartnershipAdminListResponse,
    PartnershipAdminResponse,
    PartnershipStatusUpdateRequest,
    UpdateStatusRequest,
)
from md_backend.routes.content_router import content_router
from md_backend.routes.resource_router import resource_router
from md_backend.routes.subject_router import subject_router
from md_backend.routes.upload_router import admin_upload_router
from md_backend.services.admin_service import AdminService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_superadmin

admin_service = AdminService()

admin_router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(get_current_superadmin)],
)

_ALLOWED_STATUSES = {"waiting", "approved", "rejected"}
_ALLOWED_ROLES = {"student", "admin", "guardian", "company"}


@admin_router.get("/users")
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


@admin_router.patch("/users/{user_id}/status")
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


_ALLOWED_PARTNERSHIP_STATUSES = {"pending", "approved", "rejected"}


@admin_router.get(
    "/partnerships",
    response_model=PartnershipAdminListResponse,
    summary="List all partnerships for auditing",
)
async def list_partnerships(
    session: AsyncSession = Depends(get_db_session),
    partnership_status: str | None = None,
) -> JSONResponse:
    """GET /admin/partnerships — list all contracts, optionally filtered by status."""
    if partnership_status is not None and partnership_status not in _ALLOWED_PARTNERSHIP_STATUSES:
        return JSONResponse(
            content={"detail": "Invalid status. Use: pending, approved or rejected."},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    result = await admin_service.list_partnerships(
        session=session,
        status_filter=partnership_status,
    )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@admin_router.patch(
    "/partnerships/{partnership_id}/status",
    response_model=PartnershipAdminResponse,
    summary="Approve or reject a partnership",
)
async def update_partnership_status(
    partnership_id: uuid.UUID,
    request: PartnershipStatusUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """PATCH /admin/partnerships/{partnership_id}/status — approve or reject a contract."""
    result = await admin_service.update_partnership_status(
        session=session,
        partnership_id=partnership_id,
        new_status=request.status,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Partnership not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if result == "request_not_found":
        return JSONResponse(
            content={"detail": "Linked sponsorship request not found."},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


admin_router.include_router(subject_router)
admin_router.include_router(content_router, prefix="/content")
admin_router.include_router(resource_router, prefix="/contents")
admin_router.include_router(admin_upload_router, prefix="/uploads")
admin_router.include_router(admin_resource_router, prefix="/resources")
