"""Admin trail authoring routes."""

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    AddItemRequest,
    AddTransitionRequest,
    CreateManualTrailRequest,
    CreatePathRequest,
    CreateSubPathRequest,
    StructuredTrailRequest,
    UpdateManualTrailRequest,
)
from md_backend.models.db_models import DifficultyEnum, TypeItemEnum
from md_backend.services.trail.authoring_service import TrailAuthoringService
from md_backend.services.trail.generation_service import ContentGenerationService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_superadmin

trail_authoring_router = APIRouter(
    prefix="/admin/trails",
    dependencies=[Depends(get_current_superadmin)],
)
_authoring_service = TrailAuthoringService()
_generation_service = ContentGenerationService()
_DIFFICULTY_MAP = {1: DifficultyEnum.EASY, 2: DifficultyEnum.MEDIUM, 3: DifficultyEnum.HARD}


@trail_authoring_router.get("")
async def list_trails(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    query: str | None = Query(default=None),
    subject_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """List adaptive trails for admin management."""
    trails = await _authoring_service.list_paths(
        session=session,
        page=page,
        page_size=page_size,
        query=query,
        subject_id=subject_id,
    )
    return JSONResponse(content=trails, status_code=status.HTTP_200_OK)


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


@trail_authoring_router.post("/structured")
async def create_structured_trail(
    request: StructuredTrailRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Create a multi-step trail and generate quiz questions for question steps."""
    try:
        result = await _authoring_service.create_structured_path(
            session=session,
            title=request.title,
            description=request.description,
            subject_id=request.subject_id,
            eixo=request.eixo,
            steps=request.steps,
            generation_service=_generation_service,
        )
    except LookupError as exc:
        return JSONResponse(
            content={"detail": str(exc)},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except ValueError as exc:
        return JSONResponse(
            content={"detail": str(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)


@trail_authoring_router.patch("/{path_id}")
async def update_trail(
    path_id: int,
    request: UpdateManualTrailRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Update adaptive trail metadata."""
    try:
        result = await _authoring_service.update_path(
            session=session,
            path_id=path_id,
            content_id=request.content_id,
            name=request.name,
            description=request.description,
        )
    except LookupError:
        return JSONResponse(
            content={"detail": "Content not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if result is None:
        return JSONResponse(
            content={"detail": "Trail not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@trail_authoring_router.patch("/{path_id}/structured")
async def replace_structured_trail(
    path_id: int,
    request: StructuredTrailRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Replace a trail structure and regenerate quiz items from related content."""
    try:
        result = await _authoring_service.replace_structured_path(
            session=session,
            path_id=path_id,
            title=request.title,
            description=request.description,
            subject_id=request.subject_id,
            eixo=request.eixo,
            steps=request.steps,
            generation_service=_generation_service,
        )
    except LookupError as exc:
        return JSONResponse(
            content={"detail": str(exc)},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except ValueError as exc:
        return JSONResponse(
            content={"detail": str(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if result is None:
        return JSONResponse(
            content={"detail": "Trail not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@trail_authoring_router.delete("/{path_id}")
async def delete_trail(
    path_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Delete an adaptive trail."""
    deleted = await _authoring_service.delete_path(session=session, path_id=path_id)
    if not deleted:
        return JSONResponse(
            content={"detail": "Trail not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)


@trail_authoring_router.post("/manual")
async def create_manual_trail(
    request: CreateManualTrailRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Create a quiz trail from an existing content record and generated questions."""
    try:
        generated = await _generation_service.generate_for_content(
            session=session,
            content_id=request.content_id,
            eixo=request.eixo,
            count=request.question_count,
            difficulty=request.difficulty,
        )
        path_id = await _authoring_service.create_path(
            session=session,
            content_id=request.content_id,
            name=request.name,
            description=request.description,
        )
        sub_path_id = await _authoring_service.add_sub_path(
            session=session,
            path_id=path_id,
            difficulty=_DIFFICULTY_MAP.get(request.difficulty, DifficultyEnum.EASY),
            order=1,
        )
        item_ids: list[int] = []
        for index, exercise_id in enumerate(generated["created_exercise_ids"], start=1):
            item_ids.append(
                await _authoring_service.add_item(
                    session=session,
                    sub_path_id=sub_path_id,
                    type_item=TypeItemEnum.EXERCISE,
                    resource_id=None,
                    exercise_id=exercise_id,
                    order=index,
                )
            )
    except LookupError:
        return JSONResponse(
            content={"detail": "Content not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(
        content={
            "path_id": path_id,
            "sub_path_id": sub_path_id,
            "exercise_ids": generated["created_exercise_ids"],
            "item_ids": item_ids,
        },
        status_code=status.HTTP_201_CREATED,
    )


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
