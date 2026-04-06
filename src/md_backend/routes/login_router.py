"""Login Router."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import LoginRequest
from md_backend.services.login_service import LoginService
from md_backend.utils.database import get_db_session

login_service = LoginService()

login_router = APIRouter(prefix="/login")


@login_router.post("")
async def login(request: LoginRequest, session: AsyncSession = Depends(get_db_session)):
    """Authenticate user and return JWT token."""
    result = await login_service.login(
        email=request.email, password=request.password, session=session
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Credenciais inválidas"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)
