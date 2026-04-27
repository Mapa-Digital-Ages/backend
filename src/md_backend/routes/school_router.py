"""School router — endpoints for managing school units."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    CreateSchoolRequest,
    SchoolListResponse,
    SchoolResponse,
    UpdateSchoolRequest,
)
from md_backend.services.school_service import SchoolService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_superadmin

school_service = SchoolService()
school_router = APIRouter(prefix="/school", tags=["School"])


@school_router.post("", status_code=status.HTTP_201_CREATED, response_model=SchoolResponse)
async def create_school(
    request: CreateSchoolRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Create a new school unit."""
    try:
        result = await school_service.create_school(
            first_name=request.first_name,
            last_name=request.last_name,
            email=str(request.email),
            password=request.password,
            is_private=request.is_private,
            requested_spots=request.requested_spots,
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


@school_router.get("", response_model=SchoolListResponse, summary="Listar escolas ativas")
async def list_schools(
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(default=1, ge=1, description="Número da página (começa em 1)"),
    size: int = Query(default=20, ge=1, le=100, description="Quantidade de itens por página"),
    name: str | None = Query(
        default=None, description="Filtro parcial por nome (case-insensitive)"
    ),
) -> JSONResponse:
    """List paginated active schools with optional filters."""
    result = await school_service.list_schools(
        session=session,
        page=page,
        size=size,
        name=name,
    )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@school_router.get(
    "/{school_id}",
    response_model=SchoolResponse,
    summary="Buscar escola por ID",
)
async def get_school(
    school_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Return a single school by ID or 404."""
    result = await school_service.get_school_by_id(school_id=school_id, session=session)

    if result is None:
        return JSONResponse(
            content={"detail": "Escola não encontrada."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@school_router.patch(
    "/{school_id}",
    response_model=SchoolResponse,
    summary="Atualizar dados da escola",
    dependencies=[Depends(get_current_superadmin)],
)
async def update_school(
    school_id: uuid.UUID,
    request: UpdateSchoolRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Partially update school fields."""
    result = await school_service.update_school(
        school_id=school_id,
        first_name=request.first_name,
        last_name=request.last_name,
        email=str(request.email) if request.email else None,
        is_private=request.is_private,
        requested_spots=request.requested_spots,
        session=session,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Escola não encontrada."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if result == "email_conflict":
        return JSONResponse(
            content={"detail": "E-mail ja cadastrado."},
            status_code=status.HTTP_409_CONFLICT,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@school_router.delete(
    "/{school_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Desativar escola (soft delete)",
    dependencies=[Depends(get_current_superadmin)],
)
async def deactivate_school(
    school_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Soft delete: deactivate school without removing data."""
    success = await school_service.deactivate_school(school_id=school_id, session=session)

    if not success:
        return JSONResponse(
            content={"detail": "Escola não encontrada."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)
