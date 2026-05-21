"""Student router for student registration endpoints."""

import datetime
import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    CalendarTaskSyncItemRequest,
    CalendarUpsertRequest,
    StudentRequest,
    StudentResponse,
    StudentUpdateRequest,
    TaskResponse,
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
):
    """Create a new student. Restricted to superadmin or approved guardian users."""
    is_superadmin = current_user.get("is_superadmin")
    is_guardian = current_user.get("is_guardian")

    if not is_superadmin and not is_guardian:
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
        await guardian_service.link_student_to_guardian(
            session=session,
            guardian_id=uuid.UUID(current_user["user_id"]),
            student_id=uuid.UUID(result["user_id"]),
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
    allowed = await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    )
    if allowed:
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

    success = await student_service.deactivate_student(session=session, student_id=student_id)

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

    metrics = await student_service.get_summary_metrics(session=session, student_id=student_id)
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


@student_router.get(
    "/{student_id}/calendar",
    summary="Weekly task calendar for a student",
    responses={
        200: {
            "description": "List of tasks for the current week (Sunday → Saturday, server UTC).",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": 42,
                            "date": "2026-05-19T14:00:00+00:00",
                            "title": "Resolver exercícios de álgebra",
                            "status": "pending",
                            "subject": {"id": 3, "label": "Matemática"},
                        }
                    ]
                }
            },
        },
        403: {"description": "Access denied — caller is not allowed to view this student."},
        404: {"description": "Student not found."},
    },
)
async def get_student_calendar(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Return the current week's non-deactivated tasks for *student_id*.

    The week is computed server-side (Sunday 00:00 UTC → Saturday 23:59 UTC).
    Each task includes the joined subject object ``{ id, label }`` so the
    frontend can populate the calendar without extra processing.

    - **200 OK** – list (possibly empty) of tasks in the current week.
    - **403 Forbidden** – caller lacks permission to access this student.
    - **404 Not Found** – no active student with the given ID exists.
    """
    denied = await _ensure_can_access_student(session, current_user, student_id)
    if denied is not None:
        return denied

    student = await student_service.get_student_by_id(session=session, student_id=student_id)
    if student is None:
        return JSONResponse(
            content={"detail": "Student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    tasks = await student_service.get_weekly_tasks(session=session, student_id=student_id)
    return JSONResponse(content=tasks, status_code=status.HTTP_200_OK)


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
                "No well-being record exists for this student on the requested date. "
                "This is an expected response when the student has not yet filled in "
                "their state for that day."
            ),
        },
        422: {"description": "Validation error — invalid student_id UUID or date format."},
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
):
    """Return a student's well-being record for a specific date.

    A **404** response is expected and intentional when the student has not yet registered
    their state for that day — the frontend should treat it as an empty/initial state.
    """
    if not await _can_read_daily_well_being(session, current_user, student_id, date):
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    record = await student_service.get_well_being(
        session=session,
        student_id=student_id,
        date=date,
    )

    if record is None:
        return JSONResponse(
            content={"detail": "Well-being record not found for the given date."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=record, status_code=status.HTTP_200_OK)


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
):
    """Return well-being records in ascending date order for a student."""
    if from_date > to_date:
        return JSONResponse(
            content={"detail": "'from' must be before or equal to 'to'."},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if not await _can_read_well_being_history(session, current_user, student_id):
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    records = await student_service.get_well_being_range(
        session=session,
        student_id=student_id,
        from_date=from_date,
        to_date=to_date,
    )
    return JSONResponse(content=records, status_code=status.HTTP_200_OK)


@student_router.put(
    "/{student_id}/well-being",
    summary="Register or update student well-being (upsert)",
    responses={
        200: {
            "description": "Well-being record created or updated.",
            "model": WellBeingResponse,
        },
        400: {"description": "Invalid humor value (must be 'bad', 'regular', or 'good')."},
        422: {
            "description": (
                "Validation error — invalid student_id UUID, out-of-range numeric fields, "
                "or malformed request body."
            )
        },
    },
)
async def upsert_student_well_being(
    student_id: uuid.UUID,
    request: WellBeingRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Atomically create or update the student's well-being state for today.

    Uses a single upsert on the composite primary key (student_id, date).
    Always returns **200 OK** regardless of whether the row was inserted or updated.
    """
    if not await _can_write_well_being(session, current_user, student_id):
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # Validate humor enum before hitting the database
    if request.humor is not None:
        try:
            HumorEnum(request.humor)
        except ValueError:
            return JSONResponse(
                content={
                    "detail": (
                        f"Invalid humor value '{request.humor}'. "
                        "Accepted values are: 'bad', 'regular', 'good'."
                    )
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    today = datetime.date.today()

    record = await student_service.upsert_well_being(
        session=session,
        student_id=student_id,
        date=today,
        humor=request.humor,
        online_activity_minutes=request.online_activity_minutes,
        sleep_hours=request.sleep_hours,
    )

    return JSONResponse(content=record, status_code=status.HTTP_200_OK)


@student_router.put(
    "/{student_id}/calendar/tasks",
    summary="Sync calendar tasks",
)
async def sync_calendar_tasks(
    student_id: uuid.UUID,
    request: list[CalendarTaskSyncItemRequest],
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Sync tasks (create/update) atomically."""
    token_student_id = current_user["user_id"]

    if str(student_id) != str(token_student_id):
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    try:
        result = await student_service.sync_calendar_tasks(
            session=session,
            student_id=student_id,
            tasks_payload=[item.model_dump() for item in request],
        )

        return JSONResponse(content=result, status_code=status.HTTP_200_OK)

    except ValueError as exc:
        return JSONResponse(
            content={"detail": str(exc)},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


@student_router.get(
    "/{student_id}/calendar/{date}",
    response_model=list[TaskResponse],
    summary="Get student tasks for a specific date",
    responses={
        200: {"description": "List of active tasks for the given date."},
        403: {"description": "Access denied."},
    },
)
async def get_calendar_day(
    student_id: uuid.UUID,
    date: datetime.date,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Return all active (non-soft-deleted) tasks for a student on a given date."""
    denied = await _ensure_can_access_student(session, current_user, student_id)
    if denied is not None:
        return denied

    tasks = await student_service.get_calendar_day(
        session=session,
        student_id=student_id,
        date=date,
    )
    return JSONResponse(content=tasks, status_code=status.HTTP_200_OK)


@student_router.put(
    "/{student_id}/calendar/{date}",
    response_model=list[TaskResponse],
    summary="Sync student tasks for a specific date (upsert + soft delete)",
    responses={
        200: {"description": "Updated list of active tasks for the given date."},
        403: {"description": "Access denied."},
    },
    description=(
        "Receives the **complete** task list for a student on a given date. "
        "Tasks present in the database but **absent from this array** will be "
        "automatically soft-deleted (their `deactivated_at` field will be set to "
        "the current timestamp). No physical DELETE is ever executed on the `tasks` table."
    ),
)
async def upsert_calendar_day(
    student_id: uuid.UUID,
    date: datetime.date,
    request: CalendarUpsertRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Sync the full task state for a student/date.

    - Tasks with an **id** → updated in place.
    - Tasks without an **id** → inserted as new.
    - Tasks existing in the DB but **omitted** from the array → soft-deleted.
    """
    denied = await _ensure_can_access_student(session, current_user, student_id)
    if denied is not None:
        return denied

    tasks_data = [t.model_dump() for t in request.tasks]

    result = await student_service.upsert_calendar_day(
        session=session,
        student_id=student_id,
        date=date,
        tasks=tasks_data,
    )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)
