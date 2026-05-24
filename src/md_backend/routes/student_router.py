"""Student router for student registration endpoints."""

import logging
import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    StudentRequest,
    StudentResponse,
    StudentUpdateRequest,
    WellBeingRequest,
    WellBeingResponse,
)
from md_backend.models.db_models import HumorEnum
from md_backend.services.guardian_service import GuardianService
from md_backend.services.student_service import StudentService
from md_backend.utils.access_control import (
    can_access_student,
    guardian_owns_student,
    is_active_student,
)
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user, get_current_superadmin

logger = logging.getLogger(__name__)

student_service = StudentService()
guardian_service = GuardianService()
student_router = APIRouter(prefix="/student")


async def _can_read_daily_well_being(
    session: AsyncSession,
    current_user: dict,
    student_id: uuid.UUID,
    date: datetime.date,
) -> bool:
    if current_user.get("is_superadmin"):
        return True

    user_id = uuid.UUID(current_user["user_id"])
    if await guardian_owns_student(session, user_id, student_id):
        return True

    return (
        user_id == student_id
        and date == datetime.date.today()
        and await is_active_student(session, user_id)
    )


async def _can_read_well_being_history(
    session: AsyncSession,
    current_user: dict,
    student_id: uuid.UUID,
) -> bool:
    if current_user.get("is_superadmin"):
        return True

    user_id = uuid.UUID(current_user["user_id"])
    return await guardian_owns_student(session, user_id, student_id)


async def _can_write_well_being(
    session: AsyncSession,
    current_user: dict,
    student_id: uuid.UUID,
) -> bool:
    user_id = uuid.UUID(current_user["user_id"])
    return user_id == student_id and await is_active_student(session, user_id)


@student_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=StudentResponse,
)
async def create_student(
    request: StudentRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> dict:
    """Create a new student. Restricted to superadmin or approved guardian users."""
    is_superadmin = current_user.get("is_superadmin")
    is_guardian = current_user.get("is_guardian")

    if not is_superadmin and not is_guardian:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    if is_guardian:
        await guardian_service.link_student_to_guardian(
            session=session,
            guardian_id=uuid.UUID(current_user["user_id"]),
            student_id=uuid.UUID(result["user_id"]),
        )

    return result


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
) -> list[dict]:
    """List active students with optional filters and pagination."""
    return await student_service.get_students(
        session=session,
        name=name,
        email=email,
        page=page,
        size=size,
    )


async def _ensure_can_access_student(
    session: AsyncSession,
    current_user: dict,
    student_id: uuid.UUID,
) -> None:
    """Authorize access to a student. Admins pass; guardians must own the student."""
    allowed = await can_access_student(
        session=session,
        current_user=current_user,
        student_id=student_id,
    )

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )


@student_router.get("/{student_id}")
async def get_student(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> dict:
    """Get a student by ID. Guardian-owners and admins only."""
    await _ensure_can_access_student(session, current_user, student_id)

    result = await student_service.get_student_by_id(
        session=session,
        student_id=student_id,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    return result


@student_router.put(
    "/{student_id}",
    dependencies=[Depends(get_current_superadmin)],
)
async def update_student(
    student_id: uuid.UUID,
    request: StudentUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> dict:
    """Update a student by ID. Guardian-owners and admins only."""
    await _ensure_can_access_student(session, current_user, student_id)

    result = await student_service.update_student(
        session=session,
        student_id=student_id,
        data=request.model_dump(exclude_unset=True),
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    return result


@student_router.delete(
    "/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_current_superadmin)],
)
async def delete_student(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> None:
    """Soft delete a student by ID. Guardian-owners and admins only."""
    await _ensure_can_access_student(session, current_user, student_id)

    success = await student_service.deactivate_student(
        session=session,
        student_id=student_id,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )


@student_router.get("/{student_id}/summary")
async def get_student_summary(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> list[dict]:
    """Headline metrics for the student's dashboard."""
    await _ensure_can_access_student(session, current_user, student_id)

    return await student_service.get_summary_metrics(
        session=session,
        student_id=student_id,
    )


@student_router.get("/{student_id}/disciplines")
async def get_student_disciplines(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> list[dict]:
    """Mastery progress per subject for the student."""
    await _ensure_can_access_student(session, current_user, student_id)

    return await student_service.get_disciplines_progress(
        session=session,
        student_id=student_id,
    )


@student_router.get("/{student_id}/tasks")
async def get_student_tasks(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> list[dict]:
    """Tasks assigned to the student."""
    await _ensure_can_access_student(session, current_user, student_id)

    return await student_service.get_tasks(
        session=session,
        student_id=student_id,
    )


@student_router.get(
    "/{student_id}/well-being",
    summary="Get student well-being for a specific date",
    responses={
        200: {
            "description": "Well-being record found for the given date.",
            "model": WellBeingResponse,
        },
        404: {
            "description": (
                "No well-being record exists for this student on the requested date."
            ),
        },
        422: {"description": "Validation error."},
    },
)
async def get_student_well_being(
    student_id: uuid.UUID,
    date: datetime.date = Query(
        ...,
        description="Date to query in YYYY-MM-DD format.",
        examples=["2024-09-01"],
    ),
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> dict:
    """Return a student's well-being record for a specific date."""
    if not await _can_read_daily_well_being(
        session,
        current_user,
        student_id,
        date,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    record = await student_service.get_well_being(
        session=session,
        student_id=student_id,
        date=date,
    )

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Well-being record not found for the given date.",
        )

    return record


@student_router.get(
    "/{student_id}/well-being/history",
    response_model=list[WellBeingResponse],
    summary="Get student well-being history for a date range",
)
async def get_student_well_being_history(
    student_id: uuid.UUID,
    from_date: datetime.date = Query(..., alias="from"),
    to_date: datetime.date = Query(..., alias="to"),
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> list[dict]:
    """Return well-being records in ascending date order for a student."""
    if from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'from' must be before or equal to 'to'.",
        )

    if not await _can_read_well_being_history(
        session,
        current_user,
        student_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return await student_service.get_well_being_range(
        session=session,
        student_id=student_id,
        from_date=from_date,
        to_date=to_date,
    )


@student_router.put(
    "/{student_id}/well-being",
    summary="Register or update student well-being (upsert)",
    responses={
        200: {
            "description": "Well-being record created or updated.",
            "model": WellBeingResponse,
        },
        400: {"description": "Invalid humor value."},
        422: {"description": "Validation error."},
    },
)
async def upsert_student_well_being(
    student_id: uuid.UUID,
    request: WellBeingRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> dict:
    """Atomically create or update the student's well-being state for today."""
    if not await _can_write_well_being(
        session,
        current_user,
        student_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if request.humor is not None:
        try:
            HumorEnum(request.humor)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid humor value '{request.humor}'. "
                    "Accepted values are: 'bad', 'regular', 'good'."
                ),
            ) from exc

    today = datetime.date.today()

    return await student_service.upsert_well_being(
        session=session,
        student_id=student_id,
        date=today,
        humor=request.humor,
        online_activity_minutes=request.online_activity_minutes,
        sleep_hours=request.sleep_hours,
    )