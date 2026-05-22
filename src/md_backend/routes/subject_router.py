"""Subject routes — mounted at /subjects and reused under /admin via admin_router."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import SubjectRequest, SubjectUpdateRequest
from md_backend.services.subject_service import SubjectService
from md_backend.utils.database import get_db_session

subject_router = APIRouter(prefix="/subjects")
subject_service = SubjectService()


@subject_router.get("")
async def list_subjects(session: AsyncSession = Depends(get_db_session)):
    """List subjects with content, trail, and task counts."""
    subjects = await subject_service.list_subjects(session=session)
    return JSONResponse(content=subjects, status_code=status.HTTP_200_OK)


@subject_router.get("/{subject_id}")
async def get_subject(subject_id: int, session: AsyncSession = Depends(get_db_session)):
    """Fetch a subject with its counts."""
    subject = await subject_service.get_subject(session=session, subject_id=subject_id)
    if subject is None:
        return JSONResponse(
            content={"detail": "Subject not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=subject, status_code=status.HTTP_200_OK)


@subject_router.post("")
async def create_subject(
    request: SubjectRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Create a subject by name and optional color."""
    subject = await subject_service.create_subject(
        session=session, name=request.name, color=request.color
    )
    if subject is None:
        return JSONResponse(
            content={"detail": "Subject name already exists"},
            status_code=status.HTTP_409_CONFLICT,
        )
    return JSONResponse(content=subject, status_code=status.HTTP_201_CREATED)


@subject_router.patch("/{subject_id}")
async def update_subject(
    subject_id: int,
    request: SubjectUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Update a subject's name and/or color."""
    result = await subject_service.update_subject(
        session=session,
        subject_id=subject_id,
        name=request.name,
        color=request.color,
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Subject not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if isinstance(result, str):
        return JSONResponse(
            content={"detail": "Subject name already exists"},
            status_code=status.HTTP_409_CONFLICT,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@subject_router.delete("/{subject_id}")
async def delete_subject(subject_id: int, session: AsyncSession = Depends(get_db_session)):
    """Delete a subject when no content or task references it."""
    result = await subject_service.delete_subject(session=session, subject_id=subject_id)
    if result == "not_found":
        return JSONResponse(
            content={"detail": "Subject not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if result != "deleted":
        return JSONResponse(
            content={"detail": "Subject has linked content or tasks"},
            status_code=status.HTTP_409_CONFLICT,
        )
    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)
