"""Register router for user registration endpoints."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import RegisterRequest
from md_backend.services.register_service import RegisterService
from md_backend.utils.database import get_db_session

register_service = RegisterService()
register_router = APIRouter(prefix="/register")


@register_router.post("/responsavel")
async def register_responsavel(
    request: RegisterRequest, session: AsyncSession = Depends(get_db_session)
):
    """Register a new user."""
    result = await register_service.register_responsavel(
        email=request.email, password=request.password, name=request.name, session=session
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Email already registered"},
            status_code=status.HTTP_409_CONFLICT,
        )
    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)

@register_router.post("/aluno")
async def register_aluno(
    request: RegisterRequest, session: AsyncSession = Depends(get_db_session)
):
    """Register a new user."""
    result = await register_service.register_aluno(
        email=request.email, password=request.password, name=request.name, session=session
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Email already registered"},
            status_code=status.HTTP_409_CONFLICT,
        )
    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)
