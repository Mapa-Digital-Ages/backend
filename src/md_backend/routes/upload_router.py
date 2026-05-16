"""Upload routes — student routes plus an admin sub-router mounted under /admin."""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import UpdateUploadRequest
from md_backend.services.storage_service import (
    PostgresBlobStorageService,
    S3StorageService,
    StorageService,
)
from md_backend.services.upload_service import UploadService
from md_backend.utils.access_control import can_access_student
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user
from md_backend.utils.settings import settings

upload_router = APIRouter()
admin_upload_router = APIRouter()

_STREAM_CHUNK = 65536


async def _iter_bytes(data: bytes, chunk_size: int = _STREAM_CHUNK):
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]


def get_storage_service(
    session: AsyncSession = Depends(get_db_session),
) -> StorageService:
    """Resolve the storage backend based on settings."""
    if settings.STORAGE_BACKEND == "s3":
        return S3StorageService(
            bucket=settings.AWS_S3_BUCKET or "",
            region=settings.AWS_S3_REGION or "",
            access_key_id=settings.AWS_ACCESS_KEY_ID,
            secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        )
    return PostgresBlobStorageService(session)


# --- Student / guardian routes ------------------------------------------------


@upload_router.post("/student/{student_id}/uploads")
async def upload_student_file(
    student_id: uuid.UUID,
    file: UploadFile = File(...),
    activity_type: str = Form(..., pattern=r"^(exercise|essay|activity)$"),
    subject_id: int | None = Form(default=None),
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
    storage: StorageService = Depends(get_storage_service),
):
    """Upload a file for a student. Requires ownership (admin or linked guardian)."""
    if not await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    ):
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    service = UploadService(storage=storage)
    result = await service.upload_student_file(
        student_id=student_id,
        file=file,
        activity_type=activity_type,
        subject_id=subject_id,
        session=session,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if isinstance(result, str):
        return JSONResponse(
            content={"detail": result},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)


@upload_router.get("/student/{student_id}/uploads")
async def list_student_uploads(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
    storage: StorageService = Depends(get_storage_service),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=100),
):
    """List uploads for a single student."""
    if not await can_access_student(
        session=session, current_user=current_user, student_id=student_id
    ):
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    service = UploadService(storage=storage)
    result = await service.get_student_uploads(
        student_id=student_id, session=session, page=page, size=size
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@upload_router.get("/uploads/{upload_id}")
async def get_upload(
    upload_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
    storage: StorageService = Depends(get_storage_service),
):
    """Get a single upload's metadata."""
    service = UploadService(storage=storage)
    result = await service.get_upload_by_id(
        upload_id=upload_id,
        requester_id=current_user["user_id"],
        session=session,
        is_superadmin=current_user.get("is_superadmin", False),
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Upload not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if result == "forbidden":
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@upload_router.get("/uploads/{upload_id}/download-url")
async def get_upload_download_url(
    upload_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
    storage: StorageService = Depends(get_storage_service),
):
    """Return a temporary signed URL (S3) or a fallback streaming URL."""
    service = UploadService(storage=storage)
    result = await service.get_download_url(
        upload_id=upload_id,
        requester_id=current_user["user_id"],
        session=session,
        is_superadmin=current_user.get("is_superadmin", False),
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Upload not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if result == "forbidden":
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@upload_router.get("/uploads/{upload_id}/content")
async def download_upload_content(
    upload_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
    storage: StorageService = Depends(get_storage_service),
):
    """Stream the file bytes for an upload."""
    service = UploadService(storage=storage)
    result = await service.get_upload_content(
        upload_id=upload_id,
        requester_id=current_user["user_id"],
        session=session,
        is_superadmin=current_user.get("is_superadmin", False),
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Upload not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if isinstance(result, str):
        return JSONResponse(
            content={"detail": "Access denied"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    upload, content = result
    safe_name = quote(upload.file_name)
    ascii_name = upload.file_name.encode("ascii", errors="replace").decode("ascii")
    return StreamingResponse(
        _iter_bytes(content),
        media_type=upload.file_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{safe_name}"
            )
        },
    )

@admin_upload_router.get("")
async def list_uploads(
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    query: str | None = None,
    correction_status: str | None = Query(default=None, alias="status"),
    activity_type: str | None = None,
):
    """List all student uploads for the admin review queue."""
    service = UploadService(storage=storage)
    result = await service.list_uploads(
        session=session,
        page=page,
        page_size=page_size,
        query=query,
        status_filter=correction_status,
        activity_type_filter=activity_type,
    )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@admin_upload_router.get("/{upload_id}")
async def get_admin_upload(
    upload_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
):
    """Get a single upload with student info for the admin correction view."""
    service = UploadService(storage=storage)
    result = await service.get_admin_upload(session=session, upload_id=upload_id)
    if result is None:
        return JSONResponse(
            content={"detail": "Upload not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@admin_upload_router.patch("/{upload_id}")
async def update_admin_upload(
    upload_id: uuid.UUID,
    request: UpdateUploadRequest,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
):
    """Update an upload's activity type, correction status, and/or subject."""
    service = UploadService(storage=storage)
    result = await service.update_upload(
        session=session,
        upload_id=upload_id,
        activity_type=request.activity_type,
        correction_status=request.status,
        subject_id=request.subject_id,
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Upload not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if isinstance(result, str):
        return JSONResponse(
            content={"detail": result},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@admin_upload_router.delete("/{upload_id}")
async def delete_admin_upload(
    upload_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(get_storage_service),
):
    """Delete a student upload."""
    service = UploadService(storage=storage)
    deleted = await service.delete_upload(session=session, upload_id=upload_id)
    if not deleted:
        return JSONResponse(
            content={"detail": "Upload not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)
