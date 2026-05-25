"""Setup router for one-time platform bootstrap (superadmin + default subjects)."""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import SetupRequest
from md_backend.services.setup_service import SetupService
from md_backend.services.subject_service import seed_default_subjects
from md_backend.utils.database import get_db_session
from md_backend.utils.settings import settings

setup_service = SetupService()

setup_router = APIRouter(prefix="/setup")


def _require_setup_token(x_setup_token: str | None) -> None:
    """Validate the setup token header."""
    if x_setup_token != settings.SETUP_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing setup token",
        )


@setup_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
async def setup(
    request: SetupRequest,
    session: AsyncSession = Depends(get_db_session),
    x_setup_token: str | None = Header(default=None, alias="X-Setup-Token"),
) -> JSONResponse:
    """Create the first superadmin. Only works once."""
    _require_setup_token(x_setup_token)

    result = await setup_service.create_superadmin(
        email=request.email,
        password=request.password,
        first_name=request.first_name,
        last_name=request.last_name or "",
        phone_number=request.phone_number,
        session=session,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup already completed",
        )

    await seed_default_subjects(session)
    await session.commit()

    return JSONResponse(
        content=result,
        status_code=status.HTTP_201_CREATED,
    )


@setup_router.post("/subjects")
async def setup_subjects(
    session: AsyncSession = Depends(get_db_session),
    x_setup_token: str | None = Header(default=None, alias="X-Setup-Token"),
):
    """Seed the default subject catalog."""
    _require_setup_token(x_setup_token)

    created = await seed_default_subjects(session)

    await session.commit()

    return JSONResponse(
        content={"subjects_created": created},
        status_code=status.HTTP_201_CREATED,
    )
