"""Admin trail authoring routes."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    AddItemRequest,
    AddTransitionRequest,
    CreatePathRequest,
    CreateSubPathRequest,
)
from md_backend.services.trail.authoring_service import TrailAuthoringService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_superadmin

trail_authoring_router = APIRouter(
    prefix="/admin/trails",
    dependencies=[Depends(get_current_superadmin)],
)
_authoring_service = TrailAuthoringService()


@trail_authoring_router.post("")
async def create_path(
    request: CreatePathRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Create a trail path for existing content."""
    try:
        path_id = await _authoring_service.create_path(
            session=session,
            content_id=request.content_id,
            name=request.name,
            description=request.description,
        )
    except LookupError:
        return JSONResponse(
            content={"detail": "Content not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content={"id": path_id}, status_code=status.HTTP_201_CREATED)


@trail_authoring_router.post("/{path_id}/sub-paths")
async def add_sub_path(
    path_id: int,
    request: CreateSubPathRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Add a sub-path to a trail."""
    try:
        sub_path_id = await _authoring_service.add_sub_path(
            session=session,
            path_id=path_id,
            difficulty=request.difficulty,
            order=request.order,
        )
    except LookupError:
        return JSONResponse(
            content={"detail": "Path not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content={"id": sub_path_id}, status_code=status.HTTP_201_CREATED)


@trail_authoring_router.post("/sub-paths/{sub_path_id}/items")
async def add_item(
    sub_path_id: int,
    request: AddItemRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Add an existing resource or exercise to a sub-path."""
    try:
        item_id = await _authoring_service.add_item(
            session=session,
            sub_path_id=sub_path_id,
            type_item=request.type_item,
            resource_id=request.resource_id,
            exercise_id=request.exercise_id,
            order=request.order,
        )
    except LookupError as exc:
        return JSONResponse(
            content={"detail": str(exc)},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content={"id": item_id}, status_code=status.HTTP_201_CREATED)


@trail_authoring_router.post("/transitions")
async def add_transition(
    request: AddTransitionRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Add an adaptive transition between two sub-paths."""
    try:
        transition_id = await _authoring_service.add_transition(
            session=session,
            origin_id=request.sub_path_origin_id,
            destination_id=request.sub_path_destination_id,
            rule_type=request.rule_type,
            rule_value=request.rule_value,
        )
    except ValueError as exc:
        return JSONResponse(
            content={"detail": str(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return JSONResponse(content={"id": transition_id}, status_code=status.HTTP_201_CREATED)
