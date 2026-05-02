"""Student router for student registration endpoints."""

import datetime
import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import StudentRequest, StudentResponse, StudentUpdateRequest, WellBeingRequest, WellBeingResponse
from md_backend.models.db_models import HumorEnum
from md_backend.services.student_service import StudentService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user

student_service = StudentService()
student_router = APIRouter(prefix="/student")


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
    """Create a new student. Restricted to superadmin or approved guardian/school users."""
    if not current_user.get("is_superadmin"):
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

    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)


@student_router.get("")
async def list_students(
    session: AsyncSession = Depends(get_db_session),
    _: dict = Depends(get_current_approved_user),
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


@student_router.get("/{student_id}")
async def get_student(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _: dict = Depends(get_current_approved_user),
):
    """Get a student by ID."""
    result = await student_service.get_student_by_id(session=session, student_id=student_id)

    if result is None:
        return JSONResponse(
            content={"detail": "Student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@student_router.put("/{student_id}")
async def update_student(
    student_id: uuid.UUID,
    request: StudentUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    _: dict = Depends(get_current_approved_user),
):
    """Update a student by ID."""
    result = await student_service.update_student(
        session=session,
        student_id=student_id,
        data=request.model_dump(),
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@student_router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _: dict = Depends(get_current_approved_user),
):
    """Soft delete a student by ID."""
    success = await student_service.deactivate_student(
        session=session, student_id=student_id
    )

    if not success:
        return JSONResponse(
            content={"detail": "Student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)

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
        example="2024-09-01",
    ),
    session: AsyncSession = Depends(get_db_session),
    _: dict = Depends(get_current_approved_user),
):
    """Return the well-being record (humor, online_activity_minutes, sleep_hours) for a student
    on a specific date.

    A **404** response is expected and intentional when the student has not yet registered
    their state for that day — the frontend should treat it as an empty/initial state.
    """
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


@student_router.put(
    "/{student_id}/well-being",
    summary="Register or update student well-being (upsert)",
    responses={
        200: {
            "description": "Well-being record updated. Returned when the record already existed.",
            "model": WellBeingResponse,
        },
        201: {
            "description": "Well-being record created. Returned when no record existed for today.",
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
    _: dict = Depends(get_current_approved_user),
):
    """Atomically create or update the student's well-being state for today.

    The backend performs a single **upsert** command — no prior SELECT is executed.
    The conflict target is the composite primary key **(student_id, date)**.

    - If no record exists for today → **201 Created**.
    - If a record already exists for today → **200 OK** (updated in place, no duplicate row).
    """
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
