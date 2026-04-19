"""Student router for student registration endpoints."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import StudentRequest, StudentResponse
from md_backend.services.student_service import StudentService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user

student_service = StudentService()
student_router = APIRouter(prefix="/student")


@student_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=StudentResponse,
    responses={
        201: {"":""},
        400: {"":""},
        409: {"":""},
        422: {"":""},
    },
)
async def create_student(
    request: StudentRequest,
    session: AsyncSession = Depends(get_db_session),
    _: dict = Depends(get_current_approved_user),
):
    """Create a new student with atomic transaction across user_profile and student_profile."""
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