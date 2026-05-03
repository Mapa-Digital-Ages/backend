"""Student upload router."""

import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.services.storage_service import StorageService
from md_backend.services.student_upload_service import StudentUploadService
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user


class MockStorageService(StorageService):
    """Temporary mock storage — replace with S3StorageService in production."""

    async def upload_file(self, file_bytes: bytes, storage_key: str, content_type: str) -> str:
        """Return a placeholder URL."""
        return f"https://storage.placeholder.com/{storage_key}"


student_upload_router = APIRouter(prefix="/student")
upload_router = APIRouter(prefix="/upload")


def get_storage_service() -> StorageService:
    """Dependency that returns the storage service."""
    return MockStorageService()


@student_upload_router.post("/{student_id}/uploads")
async def upload_student_file(
    student_id: uuid.UUID,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
    storage: StorageService = Depends(get_storage_service),
):
    """Upload a file for a student."""
    service = StudentUploadService(storage=storage)
    result = await service.upload_student_file(
        student_id=student_id,
        file=file,
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


@student_upload_router.get("/{student_id}/uploads")
async def list_student_uploads(
    student_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
    page: int = Query(default=1, ge=1, description="Page number"),
    size: int = Query(default=10, ge=1, le=100, description="Page size"),
):
    """List all uploads for a student."""
    service = StudentUploadService(storage=MockStorageService())
    result = await service.get_student_uploads(
        student_id=student_id,
        session=session,
        page=page,
        size=size,
    )

    if result is None:
        return JSONResponse(
            content={"detail": "Student not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@upload_router.get("/{upload_id}")
async def get_upload(
    upload_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: dict = Depends(get_current_approved_user),
):
    """Get a single upload by ID."""
    service = StudentUploadService(storage=MockStorageService())
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