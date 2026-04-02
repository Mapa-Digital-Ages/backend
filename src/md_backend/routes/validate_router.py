"""Validate router file."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from md_backend.models.api_models import ValidateRequest
from md_backend.services.valdiate_service import ValidateService

validate_service = ValidateService()


validate_router = APIRouter(prefix="/validate")


@validate_router.post("")
async def validate(request: ValidateRequest):
    """Receive text and sender and process it."""
    num1 = request.num1
    num2 = request.num2

    result = await validate_service.process_text(num1=num1, num2=num2)

    return JSONResponse(content={"result":result}, status_code=status.HTTP_200_OK)
