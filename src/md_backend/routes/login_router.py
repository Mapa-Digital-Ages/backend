"""Login Router."""

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import LoginRequest
from md_backend.services.login_service import LoginService
from md_backend.utils.database import get_db_session
from md_backend.utils.limiter import limiter

login_service = LoginService()

login_router = APIRouter(prefix="/login")


@login_router.post("")
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Authenticate user and return JWT token."""
    ip = request.client.host if request.client else None
    result = await login_service.login(
        email=body.email, password=body.password, session=session, ip=ip
    )

    if result.get("error") == "invalid_credentials":
        return JSONResponse(
            content={"detail": "Invalid credentials"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if result.get("error"):
        return JSONResponse(
            content={"detail": result["error"]},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)
