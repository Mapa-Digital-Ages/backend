"""Student upload service."""

import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import StudentProfile, StudentUpload
from md_backend.services.storage_service import StorageService

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class StudentUploadService:
    """Service for student file uploads."""

    def __init__(self, storage: StorageService) -> None:
        """Initialize with a storage backend."""
        self.storage = storage

    def validate_file(self, file: UploadFile, file_bytes: bytes) -> str | None:
        """Validate file size and type. Returns error message or None if valid."""
        if len(file_bytes) > MAX_FILE_SIZE:
            return "File too large. Maximum size is 10MB."
        if file.content_type not in ALLOWED_TYPES:
            return f"File type '{file.content_type}' is not allowed."
        return None

    async def upload_student_file(
        self,
        student_id: uuid.UUID,
        file: UploadFile,
        session: AsyncSession,
    ) -> dict | None | str:
        """Upload file and save metadata. Returns dict, None if student not found, or error string."""
        result = await session.execute(
            select(StudentProfile).where(StudentProfile.user_id == student_id)
        )
        if result.scalar_one_or_none() is None:
            return None

        file_bytes = await file.read()

        error = self.validate_file(file, file_bytes)
        if error:
            return error

        extension = file.filename.rsplit(".", 1)[-1] if "." in file.filename else ""
        storage_key = f"students/{student_id}/{uuid.uuid4()}.{extension}"

        file_url = await self.storage.upload_file(
            file_bytes=file_bytes,
            storage_key=storage_key,
            content_type=file.content_type,
        )

        upload = StudentUpload(
            student_id=student_id,
            file_name=file.filename,
            storage_key=storage_key,
            file_url=file_url,
            file_type=file.content_type,
            file_size_bytes=len(file_bytes),
        )
        session.add(upload)
        await session.commit()
        await session.refresh(upload)

        return self._upload_to_dict(upload)

    async def get_student_uploads(
        self,
        student_id: uuid.UUID,
        session: AsyncSession,
        page: int = 1,
        size: int = 10,
    ) -> list[dict] | None:
        """List all uploads for a student with pagination. Returns None if student not found."""
        result = await session.execute(
            select(StudentProfile).where(StudentProfile.user_id == student_id)
        )
        if result.scalar_one_or_none() is None:
            return None

        uploads_result = await session.execute(
            select(StudentUpload)
            .where(StudentUpload.student_id == student_id)
            .order_by(StudentUpload.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        uploads = uploads_result.scalars().all()

        return [self._upload_to_dict(u) for u in uploads]

    async def get_upload_by_id(
        self,
        upload_id: uuid.UUID,
        requester_id: str,
        session: AsyncSession,
        is_superadmin: bool = False,
    ) -> dict | None | str:
        """Get a single upload by ID. Returns None if not found, 'forbidden' if no permission."""
        result = await session.execute(
            select(StudentUpload).where(StudentUpload.id == upload_id)
        )
        upload = result.scalar_one_or_none()

        if upload is None:
            return None

        if not is_superadmin and str(upload.student_id) != requester_id:
            return "forbidden"

        return self._upload_to_dict(upload)

    def _upload_to_dict(self, upload: StudentUpload) -> dict:
        """Map a StudentUpload to a response dict."""
        
        return {
            "id": str(upload.id),
            "student_id": str(upload.student_id),
            "file_name": upload.file_name,
            "file_url": upload.file_url,
            "file_type": upload.file_type,
            "file_size_bytes": upload.file_size_bytes,
            "created_at": upload.created_at.isoformat() if upload.created_at else None,
        }