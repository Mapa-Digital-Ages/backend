"""Student router for student registration endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import StudentRequest, StudentResponse, StudentUpdateRequest
from md_backend.models.db_models import GuardianProfile, StudentGuardian
from md_backend.services.guardian_service import GuardianService
from md_backend.services.student_service import StudentService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user, get_current_superadmin

student_service = StudentService()
guardian_service = GuardianService()
student_router = APIRouter(prefix="/student")


async def _is_active_guardian(session: AsyncSession, user_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(GuardianProfile).where(
            GuardianProfile.user_id == user_id,
            GuardianProfile.deactivated_at.is_(None),
        )
    )
    return result.scalar_one_or_none() is not None


async def _guardian_owns_student(
    session: AsyncSession, guardian_id: uuid.UUID, student_id: uuid.UUID
) -> bool:
    result = await session.execute(
        select(StudentGuardian).where(
            and_(
                StudentGuardian.guardian_id == guardian_id,
                StudentGuardian.student_id == student_id,
                StudentGuardian.deactivated_at.is_(None),
            )
        )
    )
    return result.scalar_one_or_none() is not None


@student_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=StudentResponse,
    dependencies=[Depends(get_current_superadmin)],
)
async def create_student(
    request: StudentRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new student. Allowed for superadmins and active guardians.

    When the requester is a guardian, the new student is automatically linked
    to that guardian via the ``student_guardian`` table.
    """
    is_admin = bool(current_user.get("is_superadmin"))
    user_id = uuid.UUID(current_user["user_id"])

    is_guardian = False
    if not is_admin:
        is_guardian = await _is_active_guardian(session=session, user_id=user_id)

    if not is_admin and not is_guardian:
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    result = await student_service.create_student(
        first_name=request.first_name,
        last_name=request.last_name,
        email=str(request.email),
        password=request.password,
        phone_number=request.phone_number,
        birth_date=request.birth_date,
        student_class=request.student_class,
        school_id=request.school_id,
        session=session,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Email already registered"},
            status_code=status.HTTP_409_CONFLICT,
        )

    if is_guardian:
        student_id = uuid.UUID(result["user_id"])
        await guardian_service.link_student_to_guardian(
            session=session, guardian_id=user_id, student_id=student_id
        )

    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)


@student_router.get(
    "",
    dependencies=[Depends(get_current_approved_user)],
)
async def list_students(
    session: AsyncSession = Depends(get_db_session),
    name: str | None = Query(default=None, description="Filter by first or last name"),
    email: str | None = Query(default=None, description="Filter by email"),
    page: int = Query(default=1, ge=1, description="Page number"),
    size: int = Query(default=10, ge=1, le=100, description="Page size"),
):
    """List active students with optional filters and pagination."""
    students = await student_service.get_students(
        session=session, name=name, email=email, page=page, size=size
    )
    return JSONResponse(content=students, status_code=status.HTTP_200_OK)


async def _ensure_can_access_student(
    session: AsyncSession,
    current_user: dict,
    student_id: uuid.UUID,
) -> JSONResponse | None:
    """Authorize access to a student. Admins pass; guardians must own the student."""
    if current_user.get("is_superadmin"):
        return None

    user_id = uuid.UUID(current_user["user_id"])
    if await _guardian_owns_student(
        session=session, guardian_id=user_id, student_id=student_id
    ):
        return None

    return JSONResponse(
        content={"detail": "Access denied"},
        status_code=status.HTTP_403_FORBIDDEN,
    )


@student_router.get("/{student_id}")
async def get_student(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Get a student by ID. Guardian-owners and admins only."""
    denied = await _ensure_can_access_student(session, current_user, student_id)
    if denied is not None:
        return denied

    result = await student_service.get_student_by_id(session=session, student_id=student_id)

    if result is None:
        return JSONResponse(
            content={"detail": "Student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@student_router.put(
    "/{student_id}",
    dependencies=[Depends(get_current_superadmin)],
)
async def update_student(
    student_id: uuid.UUID,
    request: StudentUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Update a student by ID. Guardian-owners and admins only."""
    denied = await _ensure_can_access_student(session, current_user, student_id)
    if denied is not None:
        return denied

    result = await student_service.update_student(
        session=session,
        student_id=student_id,
        data=request.model_dump(exclude_unset=True),
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@student_router.delete(
    "/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_current_superadmin)],
)
async def delete_student(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Soft delete a student by ID. Guardian-owners and admins only."""
    denied = await _ensure_can_access_student(session, current_user, student_id)
    if denied is not None:
        return denied

    success = await student_service.deactivate_student(
        session=session, student_id=student_id
    )

    if not success:
        return JSONResponse(
            content={"detail": "Student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)


@student_router.get("/{student_id}/summary")
async def get_student_summary(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Headline metrics for the student's dashboard."""
    denied = await _ensure_can_access_student(session, current_user, student_id)
    if denied is not None:
        return denied

    metrics = await student_service.get_summary_metrics(
        session=session, student_id=student_id
    )
    return JSONResponse(content=metrics, status_code=status.HTTP_200_OK)


@student_router.get("/{student_id}/disciplines")
async def get_student_disciplines(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Mastery progress per subject for the student."""
    denied = await _ensure_can_access_student(session, current_user, student_id)
    if denied is not None:
        return denied

    disciplines = await student_service.get_disciplines_progress(
        session=session, student_id=student_id
    )
    return JSONResponse(content=disciplines, status_code=status.HTTP_200_OK)


@student_router.get("/{student_id}/tasks")
async def get_student_tasks(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Tasks assigned to the student."""
    denied = await _ensure_can_access_student(session, current_user, student_id)
    if denied is not None:
        return denied

    tasks = await student_service.get_tasks(session=session, student_id=student_id)
    return JSONResponse(content=tasks, status_code=status.HTTP_200_OK)
