"""Trail (path) routes for the student module."""

import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.services.path_service import PathService
from md_backend.utils.access_control import can_access_student
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user

path_router = APIRouter()
_path_service = PathService()


@path_router.get("")
async def list_trails(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """List all adaptive learning trails with per-student progress."""
    allowed = await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    )
    if not allowed:
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    trails = await _path_service.list_trails(session=session, student_id=student_id)
    return JSONResponse(content=trails, status_code=status.HTTP_200_OK)


@path_router.get("/{path_id}")
async def get_trail_detail(
    student_id: uuid.UUID,
    path_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Return full detail of a trail with step statuses for the student."""
    allowed = await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    )
    if not allowed:
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    detail = await _path_service.get_trail_detail(
        session=session, student_id=student_id, path_id=path_id
    )
    if detail is None:
        return JSONResponse(
            content={"detail": "Trail not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=detail, status_code=status.HTTP_200_OK)
