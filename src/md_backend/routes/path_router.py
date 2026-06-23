"""Trail (path) routes for the student module."""

import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    StepCompleteRequest,
    ValidateStepAnswerRequest,
    ValidateStepAnswerResponse,
)
from md_backend.services.trail.progress_service import TrailProgressService
from md_backend.services.trail.read_service import TrailReadService
from md_backend.utils.access_control import can_access_student
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user

path_router = APIRouter()
_read_service = TrailReadService()
_progress_service = TrailProgressService(read_service=_read_service)


@path_router.get("")
async def list_trails(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """List all adaptive learning trails with per-student progress."""
    allowed = await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    )
    if not allowed:
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    trails = await _read_service.list_trails(session=session, student_id=student_id)
    return JSONResponse(content=trails, status_code=status.HTTP_200_OK)


@path_router.get("/subjects/{subject_id}")
async def list_subject_trails(
    student_id: uuid.UUID,
    subject_id: str,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Return all adaptive learning trail details for one subject."""
    allowed = await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    )
    if not allowed:
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    trails = await _read_service.list_subject_trail_details(
        session=session,
        student_id=student_id,
        subject_id=subject_id,
    )
    if trails is None:
        return JSONResponse(
            content={"detail": "Subject not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=trails, status_code=status.HTTP_200_OK)


@path_router.get("/{path_id}")
async def get_trail_detail(
    student_id: uuid.UUID,
    path_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Return full detail of a trail with step statuses for the student."""
    allowed = await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    )
    if not allowed:
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    detail = await _read_service.get_trail_detail(
        session=session, student_id=student_id, path_id=path_id
    )
    if detail is None:
        return JSONResponse(
            content={"detail": "Trail not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=detail, status_code=status.HTTP_200_OK)


@path_router.get("/{path_id}/steps/{sub_path_id}/questions")
async def get_step_questions(
    student_id: uuid.UUID,
    path_id: int,
    sub_path_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Return the quiz question flow for one sub-path."""
    allowed = await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    )
    if not allowed:
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    flow = await _read_service.get_question_flow(
        session=session,
        path_id=path_id,
        sub_path_id=sub_path_id,
        student_id=student_id,
    )
    if flow is None:
        return JSONResponse(
            content={"detail": "Trail not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=flow, status_code=status.HTTP_200_OK)


@path_router.get("/{path_id}/steps/{sub_path_id}/sub-steps/{sub_step_id}/questions")
async def get_sub_step_questions(
    student_id: uuid.UUID,
    path_id: int,
    sub_path_id: int,
    sub_step_id: str,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Return the question flow for one specific quiz sub-step."""
    allowed = await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    )
    if not allowed:
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    flow = await _read_service.get_question_flow(
        session=session,
        path_id=path_id,
        sub_path_id=sub_path_id,
        sub_step_id=sub_step_id,
        student_id=student_id,
    )
    if flow is None:
        return JSONResponse(
            content={"detail": "Quiz sub-step not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=flow, status_code=status.HTTP_200_OK)


@path_router.post("/{path_id}/items/{item_id}/complete")
async def complete_item(
    student_id: uuid.UUID,
    path_id: int,
    item_id: int,
    request: StepCompleteRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Complete a single sub-path item and return the updated trail detail."""
    allowed = await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    )
    if not allowed:
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    result = await _progress_service.complete(
        session=session,
        student_id=student_id,
        path_id=path_id,
        item_id=item_id,
        answers=[a.model_dump() for a in request.answers],
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Trail item not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@path_router.post(
    "/{path_id}/steps/{sub_path_id}/answers/validate",
    response_model=ValidateStepAnswerResponse,
)
async def validate_step_answer(
    student_id: uuid.UUID,
    path_id: int,
    sub_path_id: int,
    request: ValidateStepAnswerRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Validate one selected quiz alternative without exposing the answer key."""
    allowed = await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    )
    if not allowed:
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    result = await _progress_service.validate_answer(
        session=session,
        path_id=path_id,
        sub_path_id=sub_path_id,
        exercise_id=request.exercise_id,
        option_id=request.option_id,
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Answer option not found in this quiz step"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@path_router.post("/{path_id}/steps/{sub_path_id}/complete")
async def complete_step(
    student_id: uuid.UUID,
    path_id: int,
    sub_path_id: int,
    request: StepCompleteRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Grade a sub-path quiz, record attempts, and advance the trail adaptively."""
    allowed = await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    )
    if not allowed:
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    result = await _progress_service.complete(
        session=session,
        student_id=student_id,
        path_id=path_id,
        sub_path_id=sub_path_id,
        answers=[a.model_dump() for a in request.answers],
    )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@path_router.post("/{path_id}/steps/{sub_path_id}/sub-steps/{sub_step_id}/complete")
async def complete_question_sub_step(
    student_id: uuid.UUID,
    path_id: int,
    sub_path_id: int,
    sub_step_id: str,
    request: StepCompleteRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Complete one quiz group without completing sibling sub-steps."""
    allowed = await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    )
    if not allowed:
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    flow = await _read_service.get_question_flow(
        session=session,
        path_id=path_id,
        sub_path_id=sub_path_id,
        sub_step_id=sub_step_id,
        student_id=student_id,
    )
    if flow is None:
        return JSONResponse(
            content={"detail": "Quiz sub-step not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    result = await _progress_service.complete(
        session=session,
        student_id=student_id,
        path_id=path_id,
        sub_path_id=sub_path_id,
        item_ids=[int(item_id) for item_id in flow["itemIds"]],
        answers=[answer.model_dump() for answer in request.answers],
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Answers must cover every question in the sub-step"},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)
