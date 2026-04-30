"""Guardian router for responsible guardian listing and details."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    GuardianDetailResponse,
    GuardianListResponse,
    GuardianStatusInput,
)
from md_backend.services.guardian_service import GuardianService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user

guardian_service = GuardianService()
guardian_router = APIRouter(prefix="/guardians", tags=["Guardians"])


@guardian_router.get("", response_model=list[GuardianListResponse])
async def list_guardians(
    session: AsyncSession = Depends(get_db_session),
    _: dict = Depends(get_current_approved_user),
    name: str | None = Query(
        default=None,
        description="Busca parcial pelo primeiro ou último nome do responsável.",
    ),
    guardian_status: GuardianStatusInput | None = Query(
        default=None,
        description="Filtra pelo status de aprovação do responsável. Valores válidos: 'waiting', 'approved', 'rejected'.",
    ),
    page: int = Query(
        default=1,
        ge=1,
        description="Número da página para paginação.",
    ),
    size: int = Query(
        default=10,
        ge=1,
        le=100,
        description="Tamanho da página para paginação.",
    ),
):
    """List active guardians with optional filters and pagination."""

    guardians = await guardian_service.get_guardians(
        session=session,
        name=name,
        status=guardian_status,
        page=page,
        size=size,
    )
    return JSONResponse(content=guardians, status_code=status.HTTP_200_OK)
    guardians = await guardian_service.get_guardians(
        session=session,
        name=name,
        status=guardian_status,
        page=page,
        size=size,
    )
    return JSONResponse(content=guardians, status_code=status.HTTP_200_OK)


@guardian_router.get("/{guardian_id}", response_model=GuardianDetailResponse)
async def get_guardian(
    guardian_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _: dict = Depends(get_current_approved_user),
):
    """Get a guardian by ID, including linked student IDs."""

    guardian = await guardian_service.get_guardian_by_id(
        session=session, guardian_id=guardian_id
    )
    if guardian is None:
        return JSONResponse(
            content={"detail": "Responsavel nao encontrado"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=guardian, status_code=status.HTTP_200_OK)
    guardian = await guardian_service.get_guardian_by_id(
        session=session, guardian_id=guardian_id
    )
    if guardian is None:
        return JSONResponse(
            content={"detail": "Responsavel nao encontrado"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=guardian, status_code=status.HTTP_200_OK)
