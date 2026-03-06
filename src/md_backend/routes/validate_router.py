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
    text = request.text
    sender = request.sender

    final_message = await validate_service.process_text(text=text, sender=sender)

    return JSONResponse(content=final_message, status_code=status.HTTP_200_OK)
