"""Admin router for user management endpoints."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import UpdateStatusRequest
from md_backend.models.db_models import RoleEnum, UserStatus
from md_backend.services.admin_service import AdminService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_superadmin

admin_service = AdminService()
admin_router = APIRouter(prefix="/admin")


@admin_router.get("/users", dependencies=[Depends(get_current_superadmin)])
async def list_users(
    session: AsyncSession = Depends(get_db_session),
    user_status: str | None = None,
    role: str | None = None,
):
    """List all users, optionally filtered by status."""
    status_filter = None
    role_filter = None
    if user_status is not None:
        try:
            status_filter = UserStatus(user_status)
        except ValueError:
            return JSONResponse(
                content={"detail": "Status invalido."},
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
    if role is not None:
        try:
            role_filter = RoleEnum(role)
        except ValueError:
            return JSONResponse(
                content={"detail": "Role invalido."},
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

    users = await admin_service.list_users(
        session=session, status_filter=status_filter, role=role_filter
    )
    return JSONResponse(content=users, status_code=status.HTTP_200_OK)


@admin_router.patch("/users/{email}/status", dependencies=[Depends(get_current_superadmin)])
async def update_user_status(
    email: str,
    request: UpdateStatusRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Update a user's approval status."""
    new_status = UserStatus(request.status)
    result = await admin_service.update_user_status(
        session=session, email=email, new_status=new_status
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Usuario nao encontrado"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if "error" in result:
        return JSONResponse(
            content={"detail": result["error"]},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)
