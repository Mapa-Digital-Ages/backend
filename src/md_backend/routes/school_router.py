"""School router - endpoints for managing school units."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    CreateSchoolRequest,
    CreateSponsorshipRequestRequest,
    SchoolBatchResponse,
    SchoolListResponse,
    SchoolPartnershipListResponse,
    SchoolResponse,
    SponsorshipRequestListResponse,
    SponsorshipRequestResponse,
    UpdateSchoolRequest,
)
from md_backend.models.db_models import PartnershipStatusEnum
from md_backend.services.csv_processor_service import CSVHeaderError
from md_backend.services.school_service import SchoolService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user, get_current_superadmin

school_service = SchoolService()
school_router = APIRouter(prefix="/school", tags=["School"])

_VISIBLE_PARTNERSHIP_STATUSES = {"pending", "approved"}


@school_router.get("/dashboard")
async def get_school_dashboard(
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> JSONResponse:
    """Return the authenticated school's students and trail progress grouped by year."""
    if not current_user.get("is_school"):
        return JSONResponse(
            content={"detail": "Access restricted to schools."},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    result = await school_service.get_dashboard_data(
        session=session,
        school_id=uuid.UUID(current_user["user_id"]),
    )
    if result is None:
        return JSONResponse(
            content={"detail": "School not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@school_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SchoolResponse,
    dependencies=[Depends(get_current_superadmin)],
)
async def create_school(
    request: CreateSchoolRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Create a new school unit."""
    try:
        result = await school_service.create_school(
            first_name=request.first_name,
            last_name=request.last_name,
            email=str(request.email),
            password=request.password,
            phone_number=request.phone_number,
            is_private=request.is_private,
            requested_spots=request.requested_spots,
            session=session,
        )
    except IntegrityError:
        await session.rollback()
        return JSONResponse(
            content={"detail": "Integrity error while saving school."},
            status_code=status.HTTP_409_CONFLICT,
        )

    if result is None:
        return JSONResponse(
            content={"detail": "Email already registered."},
            status_code=status.HTTP_409_CONFLICT,
        )

    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)


@school_router.post(
    "/batch",
    response_model=SchoolBatchResponse,
    summary="Bulk-import schools from a CSV file",
    dependencies=[Depends(get_current_superadmin)],
)
async def import_school_batch(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Importa escolas em lote via CSV, criando os válidos e reportando os inválidos."""
    raw_content = await file.read()

    try:
        result = await school_service.import_school_batch(
            raw_content=raw_content,
            session=session,
            background_tasks=background_tasks,
        )
    except CSVHeaderError as exc:
        return JSONResponse(
            content={"detail": str(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    http_status = status.HTTP_201_CREATED if result["created"] > 0 else status.HTTP_400_BAD_REQUEST
    return JSONResponse(content=result, status_code=http_status)


@school_router.get(
    "",
    response_model=SchoolListResponse,
    summary="List active schools",
    dependencies=[Depends(get_current_approved_user)],
)
async def list_schools(
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(default=1, ge=1, description="Page number (starts at 1)"),
    size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    name: str | None = Query(default=None, description="Partial filter by name (case-insensitive)"),
) -> JSONResponse:
    """List paginated active schools with optional filters."""
    result = await school_service.list_schools(
        session=session,
        page=page,
        size=size,
        name=name,
    )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@school_router.get(
    "/{school_id}",
    response_model=SchoolResponse,
    summary="Get school by ID",
    dependencies=[Depends(get_current_approved_user)],
)
async def get_school(
    school_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Return a single school by ID or 404."""
    result = await school_service.get_school_by_id(school_id=school_id, session=session)

    if result is None:
        return JSONResponse(
            content={"detail": "School not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@school_router.patch(
    "/{school_id}",
    response_model=SchoolResponse,
    summary="Update school data",
    dependencies=[Depends(get_current_superadmin)],
)
async def update_school(
    school_id: uuid.UUID,
    request: UpdateSchoolRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Partially update school fields."""
    payload = request.model_dump(exclude_unset=True)
    result = await school_service.update_school(
        school_id=school_id,
        first_name=payload.get("first_name"),
        last_name=payload.get("last_name"),
        email=str(payload["email"]) if payload.get("email") else None,
        is_private=payload.get("is_private"),
        requested_spots=payload.get("requested_spots"),
        session=session,
        last_name_provided="last_name" in payload,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "School not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if result == "email_conflict":
        return JSONResponse(
            content={"detail": "Email already registered."},
            status_code=status.HTTP_409_CONFLICT,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@school_router.delete(
    "/{school_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Deactivate school (soft delete)",
    dependencies=[Depends(get_current_superadmin)],
)
async def deactivate_school(
    school_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse | Response:
    """Soft delete: deactivate school without removing data."""
    success = await school_service.deactivate_school(school_id=school_id, session=session)

    if not success:
        return JSONResponse(
            content={"detail": "School not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@school_router.post(
    "/{school_id}/requests",
    status_code=status.HTTP_201_CREATED,
    response_model=SponsorshipRequestResponse,
    summary="Create a sponsorship request",
)
async def create_sponsorship_request(
    school_id: uuid.UUID,
    request: CreateSponsorshipRequestRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> JSONResponse:
    """Create a sponsorship request for a school.

    Only the school itself or a superadmin may create requests.
    """
    is_own_school = str(school_id) == current_user["user_id"]
    if not current_user.get("is_superadmin") and not is_own_school:
        return JSONResponse(
            content={"detail": "Access restricted to the school owner or administrators."},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    result = await school_service.create_sponsorship_request(
        school_id=school_id,
        title=request.title,
        description=request.description,
        requested_spots=request.requested_spots,
        session=session,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "School not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)


@school_router.get(
    "/{school_id}/requests",
    response_model=SponsorshipRequestListResponse,
    summary="List sponsorship requests for a school",
)
async def list_sponsorship_requests(
    school_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> JSONResponse:
    """Return all sponsorship requests for a school.

    Only the school itself or a superadmin may list requests.
    """
    is_own_school = str(school_id) == current_user["user_id"]
    if not current_user.get("is_superadmin") and not is_own_school:
        return JSONResponse(
            content={"detail": "Access restricted to the school owner or administrators."},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    result = await school_service.list_sponsorship_requests(
        school_id=school_id,
        session=session,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "School not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@school_router.get(
    "/{school_id}/partnerships",
    response_model=SchoolPartnershipListResponse,
    summary="List the partnerships of a school",
)
async def list_school_partnerships(
    school_id: uuid.UUID,
    partnership_status: str | None = Query(
        default=None,
        description="Optional visible partnership status filter: pending or approved",
    ),
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
) -> JSONResponse:
    """Return the active partnerships accepted against a school's requests.

    Only the school itself or a superadmin may list its partnerships.
    """
    is_own_school = str(school_id) == current_user["user_id"]
    if not current_user.get("is_superadmin") and not is_own_school:
        return JSONResponse(
            content={"detail": "Access restricted to the school owner or administrators."},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if partnership_status is not None and partnership_status not in _VISIBLE_PARTNERSHIP_STATUSES:
        return JSONResponse(
            content={"detail": "Invalid status. Use: pending or approved."},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    status_filter = (
        PartnershipStatusEnum(partnership_status) if partnership_status is not None else None
    )
    result = await school_service.list_school_partnerships(
        school_id=school_id,
        session=session,
        status_filter=status_filter,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "School not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)
