"""Upload service."""

import os
import re
import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import StudentProfile, StudentUpload
from md_backend.services.storage_service import StorageService
from md_backend.utils.access_control import guardian_owns_student

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_UPLOAD_CHUNK = 65536  # 64 KB read chunks

ALLOWED_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)

# (magic_prefix, mime_type) — order matters: more specific patterns first
_MAGIC_MAP: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"%PDF", "application/pdf"),
    (b"\xd0\xcf\x11\xe0", "application/msword"),  # OLE2 compound doc (.doc)
    (b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
]


def _detect_mime(data: bytes) -> str | None:
    """Return MIME type from magic bytes, or None if unrecognised."""
    for magic, mime in _MAGIC_MAP:
        if data[: len(magic)] == magic:
            # Extra validation for OOXML (.docx): must contain [Content_Types].xml
            if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                import zipfile

                try:
                    import io

                    with zipfile.ZipFile(io.BytesIO(data)) as zf:
                        if "[Content_Types].xml" not in zf.namelist():
                            return None
                except zipfile.BadZipFile:
                    return None
            return mime
    return None


def _sanitize_filename(filename: str) -> str:
    """Strip path components and control characters; cap at 255 chars."""
    name = os.path.basename(filename)
    name = re.sub(r'[\x00-\x1f\x7f"\'\\]', "", name)
    return name[:255] or "upload"


class UploadService:
    """Service for student file uploads."""

    def __init__(self, storage: StorageService) -> None:
        """Initialize with a storage backend."""
        self.storage = storage

    async def upload_student_file(
        self,
        student_id: uuid.UUID,
        file: UploadFile,
        session: AsyncSession,
    ) -> dict | None | str:
        """Upload file and save metadata + bytes.

        Returns dict on success, None if student not found, or an error string.
        """
        result = await session.execute(
            select(StudentProfile).where(StudentProfile.user_id == student_id)
        )
        if result.scalar_one_or_none() is None:
            return None

        if not file.filename:
            return "File name is required."

        # Stream-read in chunks — aborts before buffering the entire body if oversized
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await file.read(_UPLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_SIZE:
                return "File too large. Maximum size is 10MB."
            chunks.append(chunk)
        file_bytes = b"".join(chunks)

        # Detect MIME from magic bytes — ignores client-declared Content-Type
        detected_mime = _detect_mime(file_bytes)
        if detected_mime is None or detected_mime not in ALLOWED_TYPES:
            return f"File type not allowed. Detected: {detected_mime or 'unknown'}."

        safe_filename = _sanitize_filename(file.filename)
        extension = safe_filename.rsplit(".", 1)[-1] if "." in safe_filename else ""
        upload_id = uuid.uuid4()
        storage_key = f"students/{student_id}/{upload_id}.{extension}"

        upload = StudentUpload(
            id=upload_id,
            student_id=student_id,
            file_name=safe_filename,
            storage_key=storage_key,
            file_type=detected_mime,
            file_size_bytes=len(file_bytes),
        )
        session.add(upload)

        await self.storage.upload_file(
            upload_id=upload_id,
            storage_key=storage_key,
            file_bytes=file_bytes,
            content_type=detected_mime,
        )

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
        """Get a single upload metadata. Returns None if missing, 'forbidden' if no permission."""
        result = await session.execute(select(StudentUpload).where(StudentUpload.id == upload_id))
        upload = result.scalar_one_or_none()

        if upload is None:
            return None

        if not await self._can_access(upload, requester_id, session, is_superadmin):
            return "forbidden"

        return self._upload_to_dict(upload)

    async def get_upload_content(
        self,
        upload_id: uuid.UUID,
        requester_id: str,
        session: AsyncSession,
        is_superadmin: bool = False,
    ) -> tuple[StudentUpload, bytes] | None | str:
        """Fetch upload metadata + bytes. Returns (upload, content), None, or 'forbidden'."""
        result = await session.execute(select(StudentUpload).where(StudentUpload.id == upload_id))
        upload = result.scalar_one_or_none()

        if upload is None:
            return None

        if not await self._can_access(upload, requester_id, session, is_superadmin):
            return "forbidden"

        content = await self.storage.read_file(
            upload_id=upload.id,
            storage_key=upload.storage_key,
        )
        if content is None:
            return None

        return upload, content

    async def _can_access(
        self,
        upload: StudentUpload,
        requester_id: str,
        session: AsyncSession,
        is_superadmin: bool,
    ) -> bool:
        """Return True if the requester may access this upload."""
        if is_superadmin:
            return True
        if str(upload.student_id) == requester_id:
            return True
        # Allow guardian who owns the student
        try:
            guardian_id = uuid.UUID(requester_id)
        except ValueError:
            return False
        return await guardian_owns_student(
            session=session,
            guardian_id=guardian_id,
            student_id=upload.student_id,
        )

    def _upload_to_dict(self, upload: StudentUpload) -> dict:
        """Map a StudentUpload to a response dict."""
        return {
            "id": str(upload.id),
            "student_id": str(upload.student_id),
            "file_name": upload.file_name,
            "download_url": f"/uploads/{upload.id}/content",
            "file_type": upload.file_type,
            "file_size_bytes": upload.file_size_bytes,
            "created_at": upload.created_at.isoformat() if upload.created_at else None,
        }
