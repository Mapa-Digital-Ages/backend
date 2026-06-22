"""Content routes — mounted under /admin via admin_router."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import ContentUpsertRequest
from md_backend.services.content_service import ContentService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_superadmin

content_router = APIRouter(dependencies=[Depends(get_current_superadmin)])
content_service = ContentService()


@content_router.get("")
async def list_contents(
    session: AsyncSession = Depends(get_db_session),
    page: int = 1,
    page_size: int = 10,
    query: str | None = None,
):
    """List content records."""
    result = await content_service.list_contents(
        session=session, page=page, page_size=page_size, query=query
    )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@content_router.get("/{content_id}")
async def get_content(content_id: int, session: AsyncSession = Depends(get_db_session)):
    """Fetch a single content record."""
    result = await content_service.get_content(session=session, content_id=content_id)
    if result is None:
        return JSONResponse(
            content={"detail": "Content not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@content_router.post("")
async def create_content(
    request: ContentUpsertRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Create a content record."""
    result = await content_service.create_content(
        session=session,
        subject_id=request.subject_id,
        title=request.title,
        description=request.description,
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Subject not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)


@content_router.patch("/{content_id}")
async def update_content(
    content_id: int,
    request: ContentUpsertRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Update a content record."""
    result = await content_service.update_content(
        session=session,
        content_id=content_id,
        subject_id=request.subject_id,
        title=request.title,
        description=request.description,
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Content or subject not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@content_router.delete("/{content_id}")
async def delete_content(content_id: int, session: AsyncSession = Depends(get_db_session)):
    """Delete a content record."""
    deleted = await content_service.delete_content(session=session, content_id=content_id)
    if not deleted:
        return JSONResponse(
            content={"detail": "Content not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
