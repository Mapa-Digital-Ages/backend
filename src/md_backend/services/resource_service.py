"""Resource service — student-facing read operations and admin CRUD."""

import math

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import Resource, ResourceTypeEnum
from md_backend.services.storage_service import StorageService

# Types that require a presigned URL instead of the raw file_url
_CLOSED_TYPES = {
    ResourceTypeEnum.PDF,
    ResourceTypeEnum.VIDEO,
    ResourceTypeEnum.PRESENTATION,
    ResourceTypeEnum.DOCUMENT,
}

PRESIGNED_URL_EXPIRES_IN = 300  # seconds


class ResourceService:
    """Resource queries for both student access and admin management."""

    # Student-facing (read-only)
    async def list_resources_by_content(
        self,
        session: AsyncSession,
        content_id: int,
    ) -> list[dict]:
        """Return the lightweight resource list for a content block."""
        rows = (
            (
                await session.execute(
                    select(Resource)
                    .where(Resource.content_id == content_id)
                    .order_by(Resource.id.asc())
                )
            )
            .scalars()
            .all()
        )

        return [_serialize_summary(r) for r in rows]

    async def get_download_url(
        self,
        session: AsyncSession,
        resource_id: int,
        storage: StorageService,
    ) -> dict | None:
        """Return the access URL for a resource.

        - External links (type=link): return ``file_url`` as-is.
        - Closed files (pdf, video, …): generate a presigned URL via the
          storage backend; fall back to ``file_url`` when the backend does
          not support presigned URLs (e.g. Postgres blob storage).
        Returns ``None`` when the resource does not exist.
        """
        resource = await session.get(Resource, resource_id)
        if resource is None:
            return None

        if resource.type == ResourceTypeEnum.LINK:
            return {"url": resource.file_url, "expires_in": None}

        # Closed file — attempt a presigned URL
        presigned: str | None = None
        if resource.storage_key:
            import uuid as _uuid

            presigned = await storage.generate_download_url(
                upload_id=_uuid.UUID(int=0),  # unused by S3 impl, key is enough
                storage_key=resource.storage_key,
                expires_in=PRESIGNED_URL_EXPIRES_IN,
            )

        url = presigned if presigned else resource.file_url
        expires_in = PRESIGNED_URL_EXPIRES_IN if presigned else None
        return {"url": url, "expires_in": expires_in}

    # Admin-facing
    async def list_resources(
        self,
        session: AsyncSession,
        page: int = 1,
        page_size: int = 10,
        content_id: int | None = None,
        query: str | None = None,
    ) -> dict:
        """Return a paginated list of resources with optional filters."""
        stmt = select(Resource)

        if content_id is not None:
            stmt = stmt.where(Resource.content_id == content_id)

        if query:
            pattern = f"%{query.strip().lower()}%"
            stmt = stmt.where(func.lower(Resource.title).like(pattern))

        total = (
            await session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        stmt = stmt.order_by(Resource.id.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await session.execute(stmt)).scalars().all()

        return {
            "items": [_serialize_full(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": max(1, math.ceil(total / page_size)) if total else 1,
        }

    async def get_resource(self, session: AsyncSession, resource_id: int) -> dict | None:
        """Fetch the full detail of a single resource."""
        resource = await session.get(Resource, resource_id)
        if resource is None:
            return None
        return _serialize_full(resource)

    async def update_resource(
        self,
        session: AsyncSession,
        resource_id: int,
        title: str | None = None,
    ) -> dict | None:
        """Update metadata-only fields of a resource.

        Storage fields (``storage_key``, ``file_url``, ``file_name``,
        ``file_type``, ``file_size_bytes``) are never touched here.
        Returns ``None`` when the resource does not exist.
        """
        resource = await session.get(Resource, resource_id)
        if resource is None:
            return None

        if title is not None:
            resource.title = title.strip()

        await session.commit()
        await session.refresh(resource)
        return _serialize_full(resource)

    async def delete_resource(
        self,
        session: AsyncSession,
        resource_id: int,
        storage: StorageService,
    ) -> dict:
        """Delete a resource — cloud file first, then DB row.

        Returns a result dict with key ``status``:
        - ``"deleted"``  → success (200)
        - ``"not_found"`` → resource does not exist (404)
        - ``"storage_error"`` → cloud deletion raised an unexpected exception (500)

        The DB row is only removed after the storage deletion completes without
        error, preventing orphaned files in the cloud.
        Links (type=link) have no physical file; storage deletion is skipped.
        """
        import uuid as _uuid

        resource = await session.get(Resource, resource_id)
        if resource is None:
            return {"status": "not_found"}

        # Only attempt cloud deletion for resources that own a physical file
        if resource.storage_key:
            try:
                await storage.delete_file(
                    upload_id=_uuid.UUID(int=0),
                    storage_key=resource.storage_key,
                )
            except Exception as exc:
                # Bubble up so the row is NOT deleted — file would become orphaned
                return {"status": "storage_error", "detail": str(exc)}

        await session.delete(resource)
        await session.commit()
        return {"status": "deleted"}


# Serialisers
def _serialize_summary(resource: Resource) -> dict:
    """Lightweight payload: id, title, type, created_at only."""
    return {
        "id": resource.id,
        "title": resource.title,
        "type": resource.type,
        "created_at": resource.created_at.isoformat() if resource.created_at else None,
    }


def _serialize_full(resource: Resource) -> dict:
    """Full admin payload including all metadata fields."""
    return {
        "id": resource.id,
        "content_id": resource.content_id,
        "type": resource.type,
        "title": resource.title,
        "file_name": resource.file_name,
        "file_type": resource.file_type,
        "file_size_bytes": resource.file_size_bytes,
        "storage_key": resource.storage_key,
        "file_url": resource.file_url,
        "created_at": resource.created_at.isoformat() if resource.created_at else None,
        "updated_at": resource.updated_at.isoformat() if resource.updated_at else None,
    }
