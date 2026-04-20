"""School router — endpoints for managing school units."""

from fastapi import APIRouter, Depends, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import CreateSchoolRequest, SchoolListResponse, SchoolResponse
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

@school_router.get(
    "",
    response_model=SchoolListResponse,
    summary="Listar escolas ativas",
    responses={200: {"description": "Lista paginada de escolas ativas"}},
)
async def list_schools(
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(default=1, ge=1, description="Número da página"),
    size: int = Query(default=20, ge=1, le=100, description="Itens por página"),
    name: str | None = Query(default=None, description="Filtro parcial por nome (case-insensitive)"),
    cnpj: str | None = Query(default=None, description="Filtro por CNPJ exato"),
) -> JSONResponse:
    """GET /school — lista escolas ativas com paginação e filtros opcionais."""
    result = await school_service.list_schools(
        session=session,
        page=page,
        size=size,
        name=name,
        cnpj=cnpj,
    )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@school_router.get(
    "/{school_id}",
    response_model=SchoolResponse,
    summary="Buscar escola por ID",
    responses={
        200: {"description": "Dados completos da escola"},
        404: {"description": "Escola não encontrada"},
    },
)
async def get_school(
    school_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """GET /school/{school_id} — retorna a escola pelo ID ou 404."""
    result = await school_service.get_school_by_id(school_id=school_id, session=session)

    if result is None:
        return JSONResponse(
            content={"detail": "Escola não encontrada."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)
