"""Guardian router for guardian management endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    GuardianCreateRequest,
    GuardianListPaginatedResponse,
    GuardianResponse,
    GuardianUpdateRequest,
)
from md_backend.services.guardian_service import GuardianService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user, get_current_superadmin

guardian_service = GuardianService()
guardian_router = APIRouter(prefix="/guardian")


@guardian_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=GuardianResponse,
    dependencies=[Depends(get_current_superadmin)],
)
async def create_guardian(
    request: GuardianCreateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new guardian (admin only)."""
    result = await guardian_service.create_guardian(
        first_name=request.first_name,
        last_name=request.last_name,
        email=str(request.email),
        password=request.password,
        phone_number=request.phone_number,
        session=session,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Email already registered"},
            status_code=status.HTTP_409_CONFLICT,
        )

    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)


@guardian_router.get(
    "",
    response_model=GuardianListPaginatedResponse,
    dependencies=[Depends(get_current_superadmin)],
)
async def list_guardians(
    session: AsyncSession = Depends(get_db_session),
    name: str | None = Query(default=None, description="Filter by first or last name"),
    email: str | None = Query(default=None, description="Filter by email"),
    guardian_status: str | None = Query(
        default=None, description="Filter by status: waiting, approved, rejected"
    ),
    page: int = Query(default=1, ge=1, description="Page number"),
    size: int = Query(default=10, ge=1, le=100, description="Page size"),
):
    """List guardians with optional filters and pagination (admin only)."""
    guardians = await guardian_service.get_guardians(
        session=session, name=name, email=email, status=guardian_status, page=page, size=size
    )
    return JSONResponse(content=guardians, status_code=status.HTTP_200_OK)


@guardian_router.get("/me", response_model=GuardianResponse)
async def get_my_guardian(
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Return the authenticated guardian's profile and linked students."""
    result = await guardian_service.get_guardian_by_id(
        session=session, guardian_id=uuid.UUID(current_user["user_id"])
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Responsável não encontrado"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@guardian_router.patch("/me", response_model=GuardianResponse)
async def update_my_guardian(
    request: GuardianUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Update the authenticated guardian's own profile."""
    result = await guardian_service.update_guardian(
        session=session,
        guardian_id=uuid.UUID(current_user["user_id"]),
        data=request.model_dump(exclude_unset=True),
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Guardian not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if result == "email_conflict":
        return JSONResponse(
            content={"detail": "Email already in use"},
            status_code=status.HTTP_409_CONFLICT,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@guardian_router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_guardian(
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Deactivate the authenticated guardian's own account."""
    success = await guardian_service.deactivate_guardian(
        session=session, guardian_id=uuid.UUID(current_user["user_id"])
    )

    if not success:
        return JSONResponse(
            content={"detail": "Guardian not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)


@guardian_router.get(
    "/{guardian_id}",
    response_model=GuardianResponse,
    dependencies=[Depends(get_current_superadmin)],
)
async def get_guardian(
    guardian_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
):
    """Get a single guardian by ID (admin only)."""
    result = await guardian_service.get_guardian_by_id(session=session, guardian_id=guardian_id)

    if result is None:
        return JSONResponse(
            content={"detail": "Guardian not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@guardian_router.patch(
    "/{guardian_id}",
    response_model=GuardianResponse,
    dependencies=[Depends(get_current_superadmin)],
)
async def update_guardian(
    guardian_id: uuid.UUID,
    request: GuardianUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Update a guardian's profile (admin only)."""
    result = await guardian_service.update_guardian(
        session=session,
        guardian_id=guardian_id,
        data=request.model_dump(exclude_unset=True),
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Guardian not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if result == "email_conflict":
        return JSONResponse(
            content={"detail": "Email already in use"},
            status_code=status.HTTP_409_CONFLICT,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@guardian_router.delete(
    "/{guardian_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_current_superadmin)],
)
async def delete_guardian(
    guardian_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
):
    """Deactivate a guardian (admin only)."""
    success = await guardian_service.deactivate_guardian(session=session, guardian_id=guardian_id)

    if not success:
        return JSONResponse(
            content={"detail": "Guardian not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)


@guardian_router.post(
    "/{guardian_id}/students/{student_id}",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superadmin)],
)
async def link_student_to_guardian(
    guardian_id: uuid.UUID,
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
):
    """Link a student to a guardian (admin only)."""
    success = await guardian_service.link_student_to_guardian(
        session=session, guardian_id=guardian_id, student_id=student_id
    )

    if not success:
        return JSONResponse(
            content={"detail": "Guardian or student not found, or already linked"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(
        content={"detail": "Student linked to guardian successfully"},
        status_code=status.HTTP_201_CREATED,
    )


@guardian_router.delete(
    "/{guardian_id}/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_current_superadmin)],
)
async def unlink_student_from_guardian(
    guardian_id: uuid.UUID,
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
):
    """Unlink a student from a guardian (admin only)."""
    success = await guardian_service.unlink_student_from_guardian(
        session=session, guardian_id=guardian_id, student_id=student_id
    )

    if not success:
        return JSONResponse(
            content={"detail": "Link between guardian and student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)
