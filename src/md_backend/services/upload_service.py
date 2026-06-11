"""Upload service."""

import io
import math
import os
import re
import uuid
import zipfile

from fastapi import UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import StudentProfile, StudentUpload, Subject, UserProfile
from md_backend.services.storage_service import StorageService
from md_backend.utils.access_control import guardian_owns_student
from md_backend.utils.names import build_full_name
from md_backend.utils.settings import settings

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_UPLOAD_CHUNK = 65536  # 64 KB read chunks
UPLOAD_STORAGE_ERROR = "storage_error"

ALLOWED_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)

UPLOAD_ACTIVITY_TYPES = {"exercise", "essay", "activity"}
UPLOAD_CORRECTION_STATUSES = {"pending", "in_review", "corrected", "rejected"}
UPLOAD_ACTIVITY_LABELS = {
    "activity": "Atividade",
    "essay": "Redação",
    "exercise": "Exercício",
}

_MAGIC_MAP: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"%PDF", "application/pdf"),
    (b"\xd0\xcf\x11\xe0", "application/msword"),
    (b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
]


def _detect_mime(data: bytes) -> str | None:
    for magic, mime in _MAGIC_MAP:
        if data[: len(magic)] == magic:
            if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as zf:
                        if "[Content_Types].xml" not in zf.namelist():
                            return None
                except zipfile.BadZipFile:
                    return None
            return mime
    return None


def _sanitize_filename(filename: str) -> str:
    name = filename or ""
    # Remove backslashes immediately (invalid chars)
    name = name.replace("\\", "")
    # Extract basename to remove path prefixes like ../../etc/
    name = os.path.basename(name)
    # Remove control chars and quotes
    name = re.sub(r"[\x00-\x1f\x7f\"']", "", name)
    return name[:255] or "upload"


class UploadService:
    """Service for student file uploads."""

    def __init__(self, storage: StorageService) -> None:
        """Bind a storage backend to this service instance."""
        self.storage = storage

    async def upload_student_file(
        self,
        student_id: uuid.UUID,
        file: UploadFile,
        activity_type: str,
        session: AsyncSession,
        subject_id: int | None = None,
    ) -> dict | None | str:
        """Upload file with required activity type. Status defaults to 'pending'."""
        if activity_type not in UPLOAD_ACTIVITY_TYPES:
            return "invalid_activity_type"

        result = await session.execute(
            select(StudentProfile).where(StudentProfile.user_id == student_id)
        )
        if result.scalar_one_or_none() is None:
            return None

        if subject_id is not None:
            subject = await session.get(Subject, subject_id)
            if subject is None:
                return "invalid_subject"

        if not file.filename:
            return "File name is required."

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

        detected_mime = _detect_mime(file_bytes)
        if detected_mime is None or detected_mime not in ALLOWED_TYPES:
            return f"File type not allowed. Detected: {detected_mime or 'unknown'}."

        safe_filename = _sanitize_filename(file.filename)
        extension = safe_filename.rsplit(".", 1)[-1] if "." in safe_filename else ""
        upload_id = uuid.uuid4()
        storage_key = f"students/{student_id}/{upload_id}.{extension}"

        if settings.STORAGE_BACKEND == "s3":
            base_url = settings.CLOUDFRONT_URL or ""
            file_url = f"{base_url}/{storage_key}"
        else:
            file_url = f"/api/uploads/{upload_id}/content"

        upload = StudentUpload(
            id=upload_id,
            student_id=student_id,
            subject_id=subject_id,
            file_name=safe_filename,
            storage_key=storage_key,
            file_type=detected_mime,
            activity_type=activity_type,
            file_size_bytes=len(file_bytes),
            file_url=file_url,
        )
        try:
            await self.storage.upload_file(
                upload_id=upload_id,
                storage_key=storage_key,
                file_bytes=file_bytes,
                content_type=detected_mime,
            )
        except Exception:
            await session.rollback()
            return UPLOAD_STORAGE_ERROR

        session.add(upload)

        try:
            await session.commit()
        except Exception:
            await session.rollback()
            await self.storage.delete_file(upload_id=upload_id, storage_key=storage_key)
            raise
        await session.refresh(upload)
        return self._upload_to_dict(upload)

    async def get_student_uploads(
        self,
        student_id: uuid.UUID,
        session: AsyncSession,
        page: int = 1,
        size: int = 10,
    ) -> list[dict] | None:
        """List uploads for a single student."""
        result = await session.execute(
            select(StudentProfile).where(StudentProfile.user_id == student_id)
        )
        if result.scalar_one_or_none() is None:
            return None

        uploads = (
            (
                await session.execute(
                    select(StudentUpload)
                    .where(StudentUpload.student_id == student_id)
                    .order_by(StudentUpload.created_at.desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            )
            .scalars()
            .all()
        )
        return [self._upload_to_dict(u) for u in uploads]

    async def get_upload_by_id(
        self,
        upload_id: uuid.UUID,
        requester_id: str,
        session: AsyncSession,
        is_superadmin: bool = False,
    ) -> dict | None | str:
        """Get a single upload's metadata with access control."""
        upload = await session.get(StudentUpload, upload_id)
        if upload is None:
            return None
        if not await self._can_access(upload, requester_id, session, is_superadmin):
            return "forbidden"
        return self._upload_to_dict(upload)

    async def get_download_url(
        self,
        upload_id: uuid.UUID,
        requester_id: str,
        session: AsyncSession,
        is_superadmin: bool = False,
        expires_in: int = 300,
    ) -> dict | None | str:
        """Return a presigned download URL or a fallback stream URL with access control."""
        upload = await session.get(StudentUpload, upload_id)
        if upload is None:
            return None
        if not await self._can_access(upload, requester_id, session, is_superadmin):
            return "forbidden"

        url = await self.storage.generate_download_url(
            upload_id=upload.id, storage_key=upload.storage_key, expires_in=expires_in
        )
        return {
            "url": url or f"/api/uploads/{upload.id}/content",
            "expires_in": expires_in,
            "file_name": upload.file_name,
            "file_type": upload.file_type,
            "presigned": url is not None,
        }

    async def get_upload_content(
        self,
        upload_id: uuid.UUID,
        requester_id: str,
        session: AsyncSession,
        is_superadmin: bool = False,
    ) -> tuple[StudentUpload, bytes] | None | str:
        """Fetch upload metadata + bytes with access control."""
        upload = await session.get(StudentUpload, upload_id)
        if upload is None:
            return None
        if not await self._can_access(upload, requester_id, session, is_superadmin):
            return "forbidden"
        content = await self.storage.read_file(upload_id=upload.id, storage_key=upload.storage_key)
        if content is None:
            return None
        return upload, content

    async def list_uploads(
        self,
        session: AsyncSession,
        page: int = 1,
        page_size: int = 10,
        query: str | None = None,
        status_filter: str | None = None,
        activity_type_filter: str | None = None,
    ) -> dict:
        """List all student uploads with filters for the admin queue."""
        if status_filter and status_filter not in UPLOAD_CORRECTION_STATUSES:
            return self._page_response([], page, page_size, 0)
        if activity_type_filter and activity_type_filter not in UPLOAD_ACTIVITY_TYPES:
            return self._page_response([], page, page_size, 0)

        stmt = (
            select(StudentUpload, UserProfile, Subject)
            .join(StudentProfile, StudentUpload.student_id == StudentProfile.user_id)
            .join(UserProfile, StudentProfile.user_id == UserProfile.id)
            .outerjoin(Subject, StudentUpload.subject_id == Subject.id)
        )
        if status_filter:
            stmt = stmt.where(StudentUpload.correction_status == status_filter)
        if activity_type_filter:
            stmt = stmt.where(StudentUpload.activity_type == activity_type_filter)
        if query:
            pattern = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(StudentUpload.file_name).like(pattern),
                    func.lower(UserProfile.first_name).like(pattern),
                    func.lower(UserProfile.last_name).like(pattern),
                )
            )

        total = (
            await session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            await session.execute(
                stmt.order_by(StudentUpload.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()

        items = [self._to_admin_dict(upload, user, subject) for upload, user, subject in rows]
        return self._page_response(items, page, page_size, total)

    async def get_admin_upload(self, session: AsyncSession, upload_id: uuid.UUID) -> dict | None:
        """Get a single upload with student info for the admin correction view."""
        row = await self._load_admin_row(session, upload_id)
        if row is None:
            return None
        upload, user, subject = row
        return self._to_admin_dict(upload, user, subject)

    async def update_upload(
        self,
        session: AsyncSession,
        upload_id: uuid.UUID,
        activity_type: str | None = None,
        correction_status: str | None = None,
        subject_id: int | None = None,
    ) -> dict | None | str:
        """Update activity type, correction status, and/or subject on a student upload."""
        if activity_type is not None and activity_type not in UPLOAD_ACTIVITY_TYPES:
            return "invalid_activity_type"
        if correction_status is not None and correction_status not in UPLOAD_CORRECTION_STATUSES:
            return "invalid_status"

        row = await self._load_admin_row(session, upload_id)
        if row is None:
            return None

        upload, user, subject = row
        if activity_type is not None:
            upload.activity_type = activity_type
        if correction_status is not None:
            upload.correction_status = correction_status
        if subject_id is not None:
            new_subject = await session.get(Subject, subject_id)
            if new_subject is None:
                return "invalid_subject"
            upload.subject_id = subject_id
            subject = new_subject

        await session.commit()
        await session.refresh(upload)
        return self._to_admin_dict(upload, user, subject)

    async def delete_upload(self, session: AsyncSession, upload_id: uuid.UUID) -> bool:
        """Delete a student upload."""
        upload = await session.get(StudentUpload, upload_id)
        if upload is None:
            return False
        await session.delete(upload)
        await session.commit()
        return True

    async def _load_admin_row(
        self, session: AsyncSession, upload_id: uuid.UUID
    ) -> tuple[StudentUpload, UserProfile, Subject | None] | None:
        row = (
            await session.execute(
                select(StudentUpload, UserProfile, Subject)
                .join(StudentProfile, StudentUpload.student_id == StudentProfile.user_id)
                .join(UserProfile, StudentProfile.user_id == UserProfile.id)
                .outerjoin(Subject, StudentUpload.subject_id == Subject.id)
                .where(StudentUpload.id == upload_id)
            )
        ).one_or_none()
        if row is None:
            return None
        upload, user, subject = row
        return upload, user, subject

    async def _can_access(
        self,
        upload: StudentUpload,
        requester_id: str,
        session: AsyncSession,
        is_superadmin: bool,
    ) -> bool:
        if is_superadmin:
            return True
        if str(upload.student_id) == requester_id:
            return True
        try:
            guardian_id = uuid.UUID(requester_id)
        except ValueError:
            return False
        return await guardian_owns_student(
            session=session, guardian_id=guardian_id, student_id=upload.student_id
        )

    def _upload_to_dict(self, upload: StudentUpload) -> dict:
        return {
            "id": str(upload.id),
            "student_id": str(upload.student_id),
            "subject_id": upload.subject_id,
            "file_name": upload.file_name,
            "download_url": f"/uploads/{upload.id}/content",
            "file_type": upload.file_type,
            "activity_type": upload.activity_type,
            "status": upload.correction_status,
            "file_size_bytes": upload.file_size_bytes,
            "created_at": upload.created_at.isoformat() if upload.created_at else None,
        }

    def _to_admin_dict(
        self,
        upload: StudentUpload,
        user: UserProfile,
        subject: Subject | None = None,
    ) -> dict:
        """Serialize an upload joined with its student profile for admin views."""
        payload = self._upload_to_dict(upload)
        payload["student_name"] = build_full_name(user.first_name, user.last_name)
        payload["activity_label"] = UPLOAD_ACTIVITY_LABELS.get(
            upload.activity_type, upload.activity_type
        )
        payload["subject"] = (
            {
                "id": str(subject.id),
                "name": subject.name,
                "slug": subject.slug,
                "color": subject.color,
            }
            if subject is not None
            else None
        )
        return payload

    def _page_response(
        self, items: list[dict], page: int, page_size: int, total_items: int
    ) -> dict:
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": max(1, math.ceil(total_items / page_size)) if total_items else 1,
        }
