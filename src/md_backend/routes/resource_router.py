"""Resource routes — student-facing read access."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.services.resource_service import ResourceService
from md_backend.services.storage_service import (
    PostgresBlobStorageService,
    S3StorageService,
    StorageService,
)
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user
from md_backend.utils.settings import settings

resource_router = APIRouter()
_resource_service = ResourceService()


def _get_storage_service(
    session: AsyncSession = Depends(get_db_session),
) -> StorageService:
    """Resolve the storage backend based on application settings."""
    should_use_s3 = settings.STORAGE_BACKEND != "postgres" and bool(
        settings.AWS_S3_BUCKET and settings.AWS_S3_REGION
    )
    if should_use_s3:
        return S3StorageService(
            bucket=settings.AWS_S3_BUCKET or "",
            region=settings.AWS_S3_REGION or "",
            access_key_id=settings.AWS_ACCESS_KEY_ID,
            secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        )
    return PostgresBlobStorageService(session)


@resource_router.get(
    "/contents/{content_id}/resources",
    summary="List resources for a content block",
    description=(
        "**Step 1 of 2** — Returns the lightweight list of resources linked to a "
        "content block. Each item exposes only `id`, `title`, `type`, and `created_at`.\n\n"
        "Use the returned `id` values to call "
        "`GET /resources/{id}/download-url` (**Step 2**) and obtain the actual "
        "access URL for each material."
    ),
    tags=["Resources"],
)
async def list_content_resources(
    content_id: int,
    session: AsyncSession = Depends(get_db_session),
    _current_user: dict = Depends(get_current_approved_user),
):
    """List resources linked to a content block. Requires a valid student token."""
    resources = await _resource_service.list_resources_by_content(
        session=session, content_id=content_id
    )
    return JSONResponse(content=resources, status_code=status.HTTP_200_OK)


@resource_router.get(
    "/resources/{resource_id}/download-url",
    summary="Get download URL for a resource",
    description=(
        "**Step 2 of 2** — Given a `resource_id` obtained from "
        "`GET /contents/{content_id}/resources`, returns the URL to access the material.\n\n"
        "- **External link** (`type = link`): returns the stored URL directly "
        "(`expires_in` will be `null`).\n"
        "- **Closed file** (`pdf`, `video`, `presentation`, `document`): the backend "
        "calls the storage provider to generate a **temporary presigned URL** valid for "
        "300 seconds. After expiry the client must request a new URL."
    ),
    tags=["Resources"],
)
async def get_resource_download_url(
    resource_id: int,
    session: AsyncSession = Depends(get_db_session),
    _current_user: dict = Depends(get_current_approved_user),
    storage: StorageService = Depends(_get_storage_service),
):
    """Return the access URL for a resource. Requires a valid student token."""
    result = await _resource_service.get_download_url(
        session=session,
        resource_id=resource_id,
        storage=storage,
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Resource not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)
