from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from md_backend.models.api_models import LoginRequest
from md_backend.services.login_service import LoginService

login_service = LoginService()

login_router = APIRouter(prefix="/login")


@login_router.post("")
async def login(request: LoginRequest):

    email = request.email
    password = request.password

    result = await login_service.login(email=email, password=password)

    if result is None:
        return JSONResponse(
            content={"detail": "Credenciais inválidas"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)