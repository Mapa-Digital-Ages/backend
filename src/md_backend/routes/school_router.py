"""School router — endpoints for managing school units."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import CreateSchoolRequest, SchoolResponse
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