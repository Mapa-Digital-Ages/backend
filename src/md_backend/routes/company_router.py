"""Company router — endpoints for managing companies."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    CompanyResponse,
    CreateCompanyRequest,
    CreatePartnershipRequest,
    PartnershipResponse,
    PublicSponsorshipRequestListResponse,
    UpdateCompanyRequest,
)
from md_backend.services.company_service import CompanyService
from md_backend.services.school_service import SchoolService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user

company_service = CompanyService()
school_service = SchoolService()
company_router = APIRouter(prefix="/company", tags=["Company"])


@company_router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(
    request: CreateCompanyRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Any:
    """POST /company — create a new company account."""
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
    return await company_service.list_companies(session=session, name=name, page=page, size=size)


@company_router.get(
    "/count",
    dependencies=[Depends(get_current_approved_user)],
)
async def count_companies(
    session: AsyncSession = Depends(get_db_session),
    name: str | None = Query(default=None, description="Filter by first or last name"),
):
    """Return the total number of active companies, optionally filtered by name."""
    total = await company_service.count_companies(session=session, name=name)
    return JSONResponse(content={"total": total}, status_code=status.HTTP_200_OK)


@company_router.get(
    "/requests",
    response_model=PublicSponsorshipRequestListResponse,
    summary="Public showcase — list open sponsorship requests for companies",
)
async def list_public_requests(
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """List all OPEN or PARTIALLY_FULFILLED sponsorship requests for companies."""
    result = await school_service.list_public_sponsorship_requests(session=session)
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


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
    """DELETE /company/{user_id} — soft delete a company by ID."""
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
    payload = request.model_dump(exclude_unset=True)
    try:
        result = await company_service.update_company(
            user_id=user_id,
            session=session,
            first_name=payload.get("first_name"),
            last_name=payload.get("last_name"),
            email=str(payload["email"]) if payload.get("email") else None,
            phone_number=payload.get("phone_number"),
            spots=payload.get("spots"),
            is_active=payload.get("is_active"),
            last_name_provided="last_name" in payload,
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


@company_router.post(
    "/{user_id}/partnerships",
    status_code=status.HTTP_201_CREATED,
    response_model=PartnershipResponse,
    summary="Create a donation intent (partnership)",
)
async def create_partnership(
    user_id: uuid.UUID,
    request: CreatePartnershipRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> JSONResponse:
    """Formalize a company's intent to donate spots to a sponsorship request.

    Only the company itself or a superadmin may create partnerships.
    Blocked if granted_spots exceeds the request's remaining_spots.
    """
    is_own_company = str(user_id) == current_user["user_id"]
    if not current_user.get("is_superadmin") and not is_own_company:
        return JSONResponse(
            content={"detail": "Access restricted to the company owner or administrators."},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    result = await company_service.create_partnership(
        company_id=user_id,
        request_id=request.request_id,
        granted_spots=request.granted_spots,
        session=session,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Company or sponsorship request not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if result == "overbooking":
        return JSONResponse(
            content={"detail": "granted_spots exceeds the remaining spots for this request."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)
