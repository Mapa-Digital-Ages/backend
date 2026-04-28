"""Company router — endpoints for managing companies."""

from fastapi import APIRouter, Depends, status, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

import uuid
from md_backend.models.api_models import CreateCompanyRequest, CompanyResponse, UpdateCompanyRequest
from md_backend.services.company_service import CompanyService
from md_backend.utils.database import get_db_session

company_service = CompanyService()
company_router = APIRouter(prefix="/company", tags=["Company"])


@company_router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(
    request: CreateCompanyRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    """
    POST /company
    
    Cria uma nova conta de empresa e seu perfil associado.
    - O campo 'available_spots' e inicializado automaticamente com o valor de 'spots'.
    - A senha e hasheada e nunca e retornada na resposta.
    - A operacao e atomica: falha em uma tabela cancela toda a criacao.
    """
    try:
        result = await company_service.create_company(
            first_name=request.first_name,
            last_name=request.last_name,
            email=str(request.email),
            password=request.password,
            spots=request.spots,
            session=session,
        )
    except IntegrityError:
        await session.rollback()
        return JSONResponse(
            content={"detail": "Erro de integridade ao salvar empresa (e-mail ja existe)."},
            status_code=status.HTTP_409_CONFLICT,
        )

    if result is None:
        return JSONResponse(
            content={"detail": "E-mail ja cadastrado."},
            status_code=status.HTTP_409_CONFLICT,
        )

    return result


@company_router.get("", response_model=list[CompanyResponse])
async def list_companies(
    name: str | None = Query(None, description="Busca parcial por nome"),
    page: int = Query(1, ge=1, description="Numero da pagina"),
    size: int = Query(10, ge=1, le=100, description="Tamanho da pagina"),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """GET /company — list all active companies with filters and pagination."""
    return await company_service.list_companies(
        session=session, 
        name=name, 
        page=page, 
        size=size
    )


@company_router.get("/{user_id}", response_model=CompanyResponse)
async def get_company(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    """GET /company/{user_id} — get company by ID."""
    result = await company_service.get_company_by_id(user_id, session)
    if result is None:
        return JSONResponse(
            content={"detail": "Empresa nao encontrada."},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return result


@company_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """
    DELETE /company/{user_id}
    
    Realiza a inativacao (Soft Delete) da empresa. 
    A operacao altera 'is_active' para false e preenche 'deactivated_at'.
    Nenhum dado e removido fisicamente do banco de dados.
    """
    success = await company_service.delete_company(user_id, session)
    if not success:
        return JSONResponse(
            content={"detail": "Empresa nao encontrada."},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@company_router.patch("/{user_id}", response_model=CompanyResponse)
async def update_company(
    user_id: uuid.UUID,
    request: UpdateCompanyRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    """PATCH /company/{user_id} — update company data with business rules."""
    try:
        result = await company_service.update_company(
            user_id=user_id,
            session=session,
            first_name=request.first_name,
            last_name=request.last_name,
            email=str(request.email) if request.email else None,
            phone_number=request.phone_number,
            spots=request.spots,
            is_active=request.is_active,
        )
    except IntegrityError:
        await session.rollback()
        return JSONResponse(
            content={"detail": "O novo e-mail ja pertence a outro registro."},
            status_code=status.HTTP_409_CONFLICT,
        )

    if result is None:
        return JSONResponse(
            content={"detail": "Empresa nao encontrada."},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return result
