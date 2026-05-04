"""Setup router for creating the first superadmin."""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import SetupRequest
from md_backend.services.setup_service import SetupService
from md_backend.utils.database import get_db_session
from md_backend.utils.settings import settings

setup_service = SetupService()
setup_router = APIRouter(prefix="/setup")


@setup_router.post("")
async def setup(
    request: SetupRequest,
    session: AsyncSession = Depends(get_db_session),
    x_setup_token: str | None = Header(default=None, alias="X-Setup-Token"),
):
    """Create the first superadmin. Only works once; requires X-Setup-Token header."""
    if x_setup_token != settings.SETUP_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing setup token",
        )
    result = await setup_service.create_superadmin(
        email=request.email,
        password=request.password,
        first_name=request.first_name,
        last_name=request.last_name,
        phone_number=request.phone_number,
        session=session,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Setup already completed"},
            status_code=status.HTTP_409_CONFLICT,
        )
    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)
