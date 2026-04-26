"""School router — endpoints for managing school units."""

from fastapi import APIRouter, Depends, status, Query
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
school_router = APIRouter(prefix="/schools", tags=["Schools"])


@school_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SchoolResponse,
    dependencies=[Depends(get_current_superadmin)],
    responses={
        201: {
            "description": "Escola criada com sucesso.",
            "model": SchoolResponse,
        },
        400: {
            "description": "Dados inválidos.",
            "content": {"application/json": {"example": {"detail": "Dados invalidos."}}},
        },
        401: {
            "description": "Token ausente ou inválido.",
            "content": {
                "application/json": {"example": {"detail": "Missing authorization header"}}
            },
        },
        403: {
            "description": "Acesso restrito a administradores.",
            "content": {
                "application/json": {
                    "example": {"detail": "Acesso restrito a administradores"}
                }
            },
        },
        409: {
            "description": "E-mail já cadastrado.",
            "content": {
                "application/json": {"example": {"detail": "E-mail ja cadastrado."}}
            },
        },
        422: {
            "description": "Formato de e-mail inválido ou campo obrigatório ausente.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "loc": ["body", "email"],
                                "msg": "value is not a valid email address",
                                "type": "value_error.email",
                            }
                        ]
                    }
                }
            },
        },
    },
    summary="Cadastrar nova unidade escolar",
    description=(
        "Cria uma nova escola de forma **atômica**: insere em `users` e em `schools` "
        "dentro da mesma transação. Se qualquer etapa falhar, um rollback completo é "
        "executado. Endpoint restrito a **Admin Global** (`is_superadmin=true`)."
    ),
)
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
    description="Retorna lista paginada de escolas com `is_active=true`. Suporta filtros por `name` (parcial, case-insensitive) e `cnpj` (exato). Campo `is_private` é booleano. `quantidade_alunos` é calculado dinamicamente.",
    responses={
        200: {"description": "Lista paginada de escolas ativas", "model": SchoolListResponse},
    },
)
async def list_schools(
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(default=1, ge=1, description="Número da página (começa em 1)"),
    size: int = Query(default=20, ge=1, le=100, description="Quantidade de itens por página"),
    name: str | None = Query(default=None, description="Filtro parcial por nome (case-insensitive)"),
    cnpj: str | None = Query(default=None, description="Filtro por CNPJ exato"),
) -> JSONResponse:
    """GET /schools — lista escolas ativas com paginação e filtros opcionais."""
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
    description="Retorna os dados completos da escola, incluindo `quantidade_alunos` calculada e o booleano `is_private`. Nunca expõe o campo de senha.",
    responses={
        200: {"description": "Dados completos da escola", "model": SchoolResponse},
        404: {
            "description": "Escola não encontrada.",
            "content": {"application/json": {"example": {"detail": "Escola não encontrada."}}},
        },
    },
)
async def get_school(
    school_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """GET /schools/{school_id} — retorna a escola pelo ID ou 404."""
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
    description="Atualização parcial (PATCH) dos dados da escola. Todos os campos são opcionais. Alterações em `first_name`/`last_name` afetam `users.name`; `is_private` e `cnpj` afetam `schools`. Se `email` já estiver em uso, retorna 409. `id`, `user_id` e `created_at` são sempre ignorados.",
    dependencies=[Depends(get_current_superadmin)],
    responses={
        200: {"description": "Escola atualizada com sucesso.", "model": SchoolResponse},
        404: {
            "description": "Escola não encontrada.",
            "content": {"application/json": {"example": {"detail": "Escola não encontrada."}}},
        },
        409: {
            "description": "E-mail já cadastrado.",
            "content": {"application/json": {"example": {"detail": "E-mail ja cadastrado."}}},
        },
        422: {"description": "Dados malformados ou e-mail em formato inválido."},
    },
)
async def update_school(
    school_id: int,
    request: UpdateSchoolRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """PATCH /schools/{school_id} — atualiza parcialmente os dados da escola."""
    result = await school_service.update_school(
        school_id=school_id,
        first_name=request.first_name,
        last_name=request.last_name,
        email=str(request.email) if request.email else None,
        is_private=request.is_private,
        cnpj=request.cnpj,
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
    summary="Desativar escola (Soft Delete)",
    description="Realiza **apenas a inativação lógica** da escola: seta `is_active=false` e preenche `deactivated_at` com o timestamp atual. **Nenhum registro é excluído fisicamente** das tabelas `users`, `schools` ou dependentes (students, parcerias). Restrito a Admin Global.",
    dependencies=[Depends(get_current_superadmin)],
    responses={
        204: {"description": "Escola desativada com sucesso."},
        404: {
            "description": "Escola não encontrada.",
            "content": {"application/json": {"example": {"detail": "Escola não encontrada."}}},
        },
    },
)
async def deactivate_school(
    school_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """DELETE /schools/{school_id} — soft delete: inativa a escola sem excluir dados."""
    success = await school_service.deactivate_school(school_id=school_id, session=session)

    if not success:
        return JSONResponse(
            content={"detail": "Escola não encontrada."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)