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


@company_router.post("")
async def create_company(
    request: CreateCompanyRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """POST /company — create a new company account."""
    # TODO: Implementar aqui?
    # TODO: Estava acompanhando o school_service.py mas aqui travei.
    
