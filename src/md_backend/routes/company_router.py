"""Company router — endpoints for managing companies."""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    CompanyResponse,
    CreateCompanyRequest,
    UpdateCompanyRequest,
)
from md_backend.services.company_service import CompanyService
from md_backend.utils.database import get_db_session

logger = logging.getLogger(__name__)

company_service = CompanyService()
company_router = APIRouter(prefix="/company", tags=["Company"])


@company_router.post(
    "",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_company(
    request: CreateCompanyRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    """Create a new company account.

    Args:
        request: Company creation payload.
        session: Database session.

    Returns:
        HTTP 201 with created company data.

        HTTP 409 if the email already exists or a database
        integrity conflict occurs.
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
    """List active companies with pagination and optional name filtering.

    Args:
        name: Optional partial name filter.
        page: Page number.
        size: Number of items per page.
        session: Database session.

    Returns:
        List of active companies.
    """
    return await company_service.list_companies(
        session=session,
        name=name,
        page=page,
        size=size,
    )


@company_router.get("/{user_id}", response_model=CompanyResponse)
async def get_company(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    """Fetch a company by user ID.

    Args:
        user_id: Company user ID.
        session: Database session.

    Returns:
        HTTP 200 with company data.

        HTTP 404 if the company does not exist.
    """
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
    """Soft delete a company.

    Args:
        user_id: Company user ID.
        session: Database session.

    Returns:
        HTTP 204 on success.

        HTTP 404 if the company does not exist.
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
    """Update a company's data.

    Args:
        user_id: Company user ID.
        request: Partial update payload.
        session: Database session.

    Returns:
        HTTP 200 with updated company data.

        HTTP 404 if the company does not exist.

        HTTP 409 if the email already belongs to another record.
    """
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