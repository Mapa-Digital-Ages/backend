"""Company router — endpoints for managing companies."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import CreateCompanyRequest
from md_backend.services.company_service import CompanyService
from md_backend.utils.database import get_db_session

company_service = CompanyService()
company_router = APIRouter(prefix="/company", tags=["Company"])


@company_router.post("", response_model=None)
async def create_company(
    request: CreateCompanyRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """POST /company — create a new company account."""
    try:
        result = await company_service.create_company(
            first_name=request.first_name,
            last_name=request.last_name,
            email=str(request.email),
            password=request.password,
            cnpj=request.cnpj,
            spots=request.spots,
            session=session,
        )
    except IntegrityError:
        await session.rollback()
        return JSONResponse(
            content={"detail": "Erro de integridade ao salvar empresa (e-mail ou CNPJ ja existe)."},
            status_code=status.HTTP_409_CONFLICT,
        )

    if result is None:
        return JSONResponse(
            content={"detail": "E-mail ja cadastrado."},
            status_code=status.HTTP_409_CONFLICT,
        )

    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)
