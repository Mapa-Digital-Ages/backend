"""School router — endpoints for managing school units."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import CreateSchoolRequest
from md_backend.services.school_service import SchoolService
from md_backend.utils.database import get_db_session

school_service = SchoolService()
school_router = APIRouter(prefix="/school", tags=["School"])


@school_router.post("")
async def create_school(
    request: CreateSchoolRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """POST /schools — create a new school unit (superadmin only)."""
    try:
        result = await school_service.create_school(
            first_name=request.first_name,
            last_name=request.last_name,
            email=str(request.email),
            password=request.password,
            is_private=request.is_private,
            cnpj=request.cnpj,
            session=session,
        )
    except IntegrityError:
        await session.rollback()
        return JSONResponse(
            content={"detail": "Erro de integridade ao salvar escola."},
            status_code=status.HTTP_409_CONFLICT,
        )

    if result is None:
        return JSONResponse(
            content={"detail": "E-mail ja cadastrado."},
            status_code=status.HTTP_409_CONFLICT,
        )

    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)
