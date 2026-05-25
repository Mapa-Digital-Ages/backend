"""Register router for user registration endpoints."""

import logging

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import RegisterRequest, StudentRegisterRequest
from md_backend.services.register_service import RegisterService
from md_backend.utils.database import get_db_session

logger = logging.getLogger(__name__)

register_service = RegisterService()

register_router = APIRouter(
    prefix="/register",
    tags=["Register"],
)


@register_router.post("/guardian")
async def register_guardian(
    request: RegisterRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Register a new guardian account."""
    result = await register_service.register_guardian(
        session=session,
        first_name=request.first_name,
        last_name=request.last_name or "",
        email=request.email,
        password=request.password,
        phone_number=request.phone_number,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Email already registered"},
            status_code=status.HTTP_409_CONFLICT,
        )

    return JSONResponse(
        content=result,
        status_code=status.HTTP_201_CREATED,
    )


@register_router.post("/student")
async def register_student(
    request: StudentRegisterRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Register a new student account."""
    result = await register_service.register_student(
        email=request.email,
        password=request.password,
        first_name=request.first_name,
        last_name=request.last_name or "",
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

    return JSONResponse(
        content=result,
        status_code=status.HTTP_201_CREATED,
    )
