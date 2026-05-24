"""Upload router."""

import logging
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

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

logger = logging.getLogger(__name__)

upload_router = APIRouter()

_STREAM_CHUNK = 65536  # 64 KB


async def _iter_bytes(data: bytes, chunk_size: int = _STREAM_CHUNK):
    """Yield data in chunks for StreamingResponse."""
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


async def _check_student_access(
    session: AsyncSession,
    current_user: dict,
    student_id: uuid.UUID,
) -> bool:
    """Return whether the current user can access the student."""
    return await can_access_student(
        session=session,
        current_user=current_user,
        student_id=student_id,
    )


@upload_router.post("/student/{student_id}/uploads")
async def upload_student_file(
    student_id: uuid.UUID,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
    storage: StorageService = Depends(get_storage_service),
):
    """Upload a file for a student."""
    if not await _check_student_access(session, current_user, student_id):
        return {"detail": "Access denied"}, 403

    service = UploadService(storage=storage)

    result = await service.upload_student_file(
        student_id=student_id,
        file=file,
        session=session,
    )

    if result is None:
        return {"detail": "Student not found"}, 404

    if isinstance(result, str):
        return {"detail": result}, 400

    return result


@upload_router.get("/student/{student_id}/uploads")
async def list_student_uploads(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
    storage: StorageService = Depends(get_storage_service),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=100),
):
    """List uploads for a student."""
    if not await _check_student_access(session, current_user, student_id):
        return {"detail": "Access denied"}, 403

    service = UploadService(storage=storage)

    result = await service.get_student_uploads(
        student_id=student_id,
        session=session,
        page=page,
        size=size,
    )

    if result is None:
        return {"detail": "Student not found"}, 404

    return result


@upload_router.get("/uploads/{upload_id}")
async def get_upload(
    upload_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
    storage: StorageService = Depends(get_storage_service),
):
    """Get upload metadata."""
    service = UploadService(storage=storage)

    result = await service.get_upload_by_id(
        upload_id=upload_id,
        requester_id=current_user["user_id"],
        session=session,
        is_superadmin=current_user.get("is_superadmin", False),
    )

    if result is None:
        return {"detail": "Upload not found"}, 404

    if result == "forbidden":
        return {"detail": "Access denied"}, 403

    return result


@upload_router.get("/uploads/{upload_id}/content")
async def download_upload_content(
    upload_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
    storage: StorageService = Depends(get_storage_service),
):
    """Download upload content."""
    service = UploadService(storage=storage)

    result = await service.get_upload_content(
        upload_id=upload_id,
        requester_id=current_user["user_id"],
        session=session,
        is_superadmin=current_user.get("is_superadmin", False),
    )

    if result is None:
        return {"detail": "Upload not found"}, 404

    if isinstance(result, str):
        return {"detail": "Access denied"}, 403

    upload, content = result

    safe_name = quote(upload.file_name)
    ascii_name = upload.file_name.encode(
        "ascii",
        errors="replace",
    ).decode("ascii")

    return StreamingResponse(
        _iter_bytes(content),
        media_type=upload.file_type,
        headers={
            "Content-Disposition": (
                f"attachment; "
                f'filename="{ascii_name}"; '
                f"filename*=UTF-8''{safe_name}"
            )
        },
    )