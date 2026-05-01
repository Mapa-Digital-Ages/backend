"""Guardian router for guardian management endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from md_backend.utils.security import get_current_approved_user

guardian_service = GuardianService()
guardian_router = APIRouter(prefix="/guardian")


def _ensure_admin_or_school(current_user: dict) -> None:
    if not current_user.get("is_superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Only administrators can access this route.",
        )


@guardian_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=GuardianResponse,
)
async def create_guardian(
    request: GuardianCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Create a new guardian (admin only)."""
    _ensure_admin_or_school(current_user)

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
)
async def list_guardians(
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
    name: str | None = Query(default=None, description="Filter by first or last name"),
    email: str | None = Query(default=None, description="Filter by email"),
    guardian_status: str | None = Query(
        default=None, description="Filter by status: waiting, approved, rejected"
    ),
    page: int = Query(default=1, ge=1, description="Page number"),
    size: int = Query(default=10, ge=1, le=100, description="Page size"),
):
    """List guardians with optional filters and pagination (admin only)."""
    _ensure_admin_or_school(current_user)
    guardians = await guardian_service.get_guardians(
        session=session, name=name, email=email, status=guardian_status, page=page, size=size
    )
    return JSONResponse(content=guardians, status_code=status.HTTP_200_OK)


@guardian_router.get("/{guardian_id}", response_model=GuardianResponse)
async def get_guardian(
    guardian_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Get a single guardian by ID (admin only)."""
    _ensure_admin_or_school(current_user)
    result = await guardian_service.get_guardian_by_id(session=session, guardian_id=guardian_id)

    if result is None:
        return JSONResponse(
            content={"detail": "Guardian not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@guardian_router.patch("/{guardian_id}", response_model=GuardianResponse)
async def update_guardian(
    guardian_id: uuid.UUID,
    request: GuardianUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Update a guardian's profile (admin only)."""
    _ensure_admin_or_school(current_user)
    result = await guardian_service.update_guardian(
        session=session,
        guardian_id=guardian_id,
        data=request.model_dump(exclude_unset=True),
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Guardian not found or email already in use"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@guardian_router.delete("/{guardian_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_guardian(
    guardian_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Deactivate a guardian (admin only)."""
    _ensure_admin_or_school(current_user)
    success = await guardian_service.deactivate_guardian(session=session, guardian_id=guardian_id)

    if not success:
        return JSONResponse(
            content={"detail": "Guardian not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)


@guardian_router.post("/{guardian_id}/students/{student_id}", status_code=status.HTTP_201_CREATED)
async def link_student_to_guardian(
    guardian_id: uuid.UUID,
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Link a student to a guardian (admin only)."""
    _ensure_admin_or_school(current_user)
    success = await guardian_service.link_student_to_guardian(
        session=session, guardian_id=guardian_id, student_id=student_id
    )

    if not success:
        return JSONResponse(
            content={"detail": "Guardian or student not found, or already linked"},
            status_code=status.HTTP_409_CONFLICT,
        )

    return JSONResponse(
        content={"detail": "Student linked to guardian successfully"},
        status_code=status.HTTP_201_CREATED,
    )


@guardian_router.delete(
    "/{guardian_id}/students/{student_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def unlink_student_from_guardian(
    guardian_id: uuid.UUID,
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Unlink a student from a guardian (admin only)."""
    _ensure_admin_or_school(current_user)
    success = await guardian_service.unlink_student_from_guardian(
        session=session, guardian_id=guardian_id, student_id=student_id
    )

    if not success:
        return JSONResponse(
            content={"detail": "Link between guardian and student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)
