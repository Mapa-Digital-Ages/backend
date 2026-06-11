"""Business logic for resource uploads and storage metadata."""

import io
import os
import re
import uuid
import zipfile

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import Content, Resource, ResourceTypeEnum
from md_backend.services.storage_service import StorageService
from md_backend.utils.settings import settings

MAX_DOCUMENT_SIZE_BYTES = 50 * 1024 * 1024
MAX_VIDEO_SIZE_BYTES = 500 * 1024 * 1024

_DOCUMENT_RESOURCE_TYPES = {
    ResourceTypeEnum.PDF,
    ResourceTypeEnum.DOCUMENT,
    ResourceTypeEnum.PRESENTATION,
}

# Magic bytes mapping for file type validation
_MAGIC_BYTES_MAP: list[tuple[bytes, str]] = [
    (b"%PDF", "application/pdf"),
    (b"\xd0\xcf\x11\xe0", "application/msword"),  # DOC
    (b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),  # DOCX
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\x00\x00\x00\x18ftypmp42", "video/mp4"),  # MP4
    (b"\x00\x00\x00\x20ftypisom", "video/mp4"),  # MP4
    (b"ID3", "audio/mpeg"),  # MP3
    (b"\xff\xfb", "audio/mpeg"),  # MP3
]


def _detect_magic_type(data: bytes) -> str | None:
    """Detect MIME type based on magic bytes signature.
    
    Args:
        data: File bytes to check
        
    Returns:
        MIME type string or None if not detected
    """
    for magic, mime_type in _MAGIC_BYTES_MAP:
        if data[: len(magic)] == magic:
            # Extra validation for DOCX/XLSX files
            if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as zf:
                        if "[Content_Types].xml" not in zf.namelist():
                            continue
                except (zipfile.BadZipFile, Exception):
                    continue
            return mime_type
    return None


def _sanitize_filename(filename: str) -> str:
    name = os.path.basename(filename or "")
    name = re.sub(r"[\x00-\x1f\x7f\"'\\]", "", name)
    return name[:255] or "resource"


def _upload_id_for_storage_key(storage_key: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, storage_key)


class ResourceService:
    """Service layer for resource persistence and storage orchestration."""

    def __init__(self, storage: StorageService) -> None:
        """Initialize ResourceService with a StorageService implementation.

        The provided `storage` is used for all storage operations (upload/delete)
        and is injected to keep the service implementation testable and backend-agnostic.
        """
        self.storage = storage

    async def upload_resource(
        self,
        session: AsyncSession,
        file_bytes: bytes,
        title: str,
        resource_type: str,
        content_id: int,
        file_name: str,
        file_type: str,
    ) -> dict | str:
        """Upload a resource file, persist it to storage and save metadata.
        
        Performs strict security validations:
        - Magic byte verification to ensure file type matches declared type
        - Size limits based on resource type
        - Title and type validation
        """
        if not title:
            return "title_required"

        if not file_type:
            return "invalid_file_type"

        try:
            resource_type_enum = ResourceTypeEnum(resource_type.strip().lower())
        except Exception:
            return "invalid_resource_type"

        if resource_type_enum == ResourceTypeEnum.VIDEO:
            max_size = MAX_VIDEO_SIZE_BYTES
        elif resource_type_enum in _DOCUMENT_RESOURCE_TYPES:
            max_size = MAX_DOCUMENT_SIZE_BYTES
        else:
            return "invalid_resource_type"

        if len(file_bytes) == 0:
            return "invalid_file"

        if len(file_bytes) > max_size:
            return "file_too_large"

        # Validate magic bytes to ensure file type matches declared type
        detected_mime = _detect_magic_type(file_bytes)
        if detected_mime is None:
            return "invalid_file_format"
        
        # Verify the detected MIME type is acceptable for this resource type
        allowed_mimes_for_type = self._get_allowed_mimes(resource_type_enum)
        if detected_mime not in allowed_mimes_for_type:
            return "file_type_mismatch"

        content = await session.get(Content, content_id)
        if content is None:
            return "invalid_content_id"

        safe_file_name = _sanitize_filename(file_name or title)
        storage_key = f"resources/{content_id}/{uuid.uuid4()}/{safe_file_name}"
        upload_id = _upload_id_for_storage_key(storage_key)

        if settings.STORAGE_BACKEND == "s3":
            base_url = settings.CLOUDFRONT_URL or ""
            file_url = f"{base_url}/{storage_key}"
        else:
            file_url = f"/api/resources/{storage_key}"

        try:
            await self.storage.upload_file(
                upload_id=upload_id,
                storage_key=storage_key,
                file_bytes=file_bytes,
                content_type=detected_mime,
            )
        except Exception:
            await session.rollback()
            return "storage_error"

        resource = Resource(
            content_id=content_id,
            type=resource_type_enum,
            title=title,
            file_name=safe_file_name,
            file_type=file_type,
            file_size_bytes=len(file_bytes),
            storage_key=storage_key,
            file_url=file_url,
        )
        session.add(resource)

        try:
            await session.commit()
        except Exception:
            await session.rollback()
            try:
                await self.storage.delete_file(upload_id=upload_id, storage_key=storage_key)
            except Exception:
                pass
            raise

        await session.refresh(resource)
        return self._resource_to_dict(resource)

    async def create_link_resource(
        self,
        session: AsyncSession,
        content_id: int,
        title: str,
        url: str,
    ) -> dict | str:
        """Create a link-type resource without file upload.
        
        Args:
            session: Database session
            content_id: Content ID to associate with
            title: Resource title
            url: URL to store
            
        Returns:
            Resource dict on success, error string on failure
        """
        if not title:
            return "title_required"
        
        if not url:
            return "url_required"
        
        content = await session.get(Content, content_id)
        if content is None:
            return "invalid_content_id"
        
        resource = Resource(
            content_id=content_id,
            type=ResourceTypeEnum.LINK,
            title=title,
            file_name=None,
            file_type=None,
            file_size_bytes=0,
            storage_key=None,
            file_url=url,
        )
        session.add(resource)
        
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        
        await session.refresh(resource)
        return self._resource_to_dict(resource)

    async def get_resource(self, session: AsyncSession, resource_id: int) -> dict | None:
        """Return resource metadata by its database identifier."""
        resource = await session.get(Resource, resource_id)
        if resource is None:
            return None
        return self._resource_to_dict(resource)

    async def list_resources(
        self,
        session: AsyncSession,
        content_id: int,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """List resources for a given content_id with pagination."""
        total = (
            await session.execute(
                select(func.count()).select_from(Resource).where(Resource.content_id == content_id)
            )
        ).scalar_one()
        result = await session.execute(
            select(Resource)
            .where(Resource.content_id == content_id)
            .order_by(Resource.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        resources = result.scalars().all()
        return {
            "items": [self._resource_to_dict(resource) for resource in resources],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    async def delete_resource(self, session: AsyncSession, resource_id: int) -> bool:
        """Delete a resource from storage and remove its database record."""
        resource = await session.get(Resource, resource_id)
        if resource is None or resource.storage_key is None:
            return False

        upload_id = _upload_id_for_storage_key(resource.storage_key)
        try:
            await self.storage.delete_file(upload_id=upload_id, storage_key=resource.storage_key)
        except Exception:
            await session.rollback()
            return False

        await session.delete(resource)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return True

    def _get_allowed_mimes(self, resource_type: ResourceTypeEnum) -> set[str]:
        """Return allowed MIME types for a given resource type.
        
        Args:
            resource_type: The ResourceTypeEnum to validate MIME types for
            
        Returns:
            Set of allowed MIME types
        """
        mime_map = {
            ResourceTypeEnum.PDF: {"application/pdf"},
            ResourceTypeEnum.DOCUMENT: {
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            },
            ResourceTypeEnum.PRESENTATION: {
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "application/vnd.ms-powerpoint",
            },
            ResourceTypeEnum.VIDEO: {"video/mp4", "video/mpeg", "video/quicktime"},
            ResourceTypeEnum.LINK: set(),  # Links don't have file MIME types
        }
        return mime_map.get(resource_type, set())

    def _resource_to_dict(self, resource: Resource) -> dict:
        return {
            "id": resource.id,
            "content_id": resource.content_id,
            "type": resource.type.value,
            "title": resource.title,
            "file_name": resource.file_name,
            "file_type": resource.file_type,
            "file_size_bytes": resource.file_size_bytes,
            "storage_key": resource.storage_key,
            "file_url": resource.file_url,
            "created_at": resource.created_at,
            "updated_at": resource.updated_at,
        }
