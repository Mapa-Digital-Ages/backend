"""Admin routes for offline content question generation."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import GenerateQuestionsRequest
from md_backend.services.trail.generation_service import ContentGenerationService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_superadmin

content_generation_router = APIRouter(
    prefix="/admin/contents",
    dependencies=[Depends(get_current_superadmin)],
)
_generation_service = ContentGenerationService()


@content_generation_router.post("/{content_id}/generate-questions")
async def generate_questions(
    content_id: int,
    request: GenerateQuestionsRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Generate and persist exercises/options for one content record."""
    try:
        result = await _generation_service.generate_for_content(
            session=session,
            content_id=content_id,
            eixo=request.eixo,
            count=request.count,
            difficulty=request.difficulty,
        )
    except LookupError:
        return JSONResponse(
            content={"detail": "Content not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)
