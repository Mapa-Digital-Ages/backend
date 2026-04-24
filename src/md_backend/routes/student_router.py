"""Student router for student registration endpoints."""

from fastapi import APIRouter, Depends, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import StudentRequest, StudentResponse, StudentListResponse
from md_backend.services.student_service import StudentService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user
from md_backend.models.api_models import StudentRequest, StudentResponse, StudentListResponse, StudentUpdateRequest

student_service = StudentService()
student_router = APIRouter(prefix="/student")


@student_router.post("")
async def create_student(
    request: StudentRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Create a new student with atomic transaction across user_profile and student_profile."""
    allowed_roles = {"admin", "responsavel", "escola"}
    if current_user.get("role") not in allowed_roles and not current_user.get("is_superadmin"):
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    result = await student_service.create_student(
        first_name=request.first_name,
        last_name=request.last_name,
        email=request.email,
        password=request.password,
        birth_date=request.birth_date,
        student_class=request.student_class,
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
    """List all active students with optional filters and pagination."""
    students = await student_service.get_students(
        session=session, name=name, email=email, page=page, size=size
    )
    return JSONResponse(content=students, status_code=status.HTTP_200_OK)


@student_router.get("/{student_id}")
async def get_student(
    student_id: int,
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
    student_id: int,
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

@student_router.delete("/{student_id}")
async def delete_student(
    student_id: int,
    session: AsyncSession = Depends(get_db_session),
    _: dict = Depends(get_current_approved_user),
):
    """Soft delete a student by ID."""
    result = await student_service.deactivate_student(
        session=session, student_id=student_id
    )

    if not result:
        return JSONResponse(
            content={"detail": "Student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(
        content={"detail": "Student deleted successfully"},
        status_code=status.HTTP_200_OK,
    )