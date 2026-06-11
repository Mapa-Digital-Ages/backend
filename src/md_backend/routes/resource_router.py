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


def _get_storage_service(
    session: AsyncSession = Depends(get_db_session),
) -> StorageService:
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


def _get_resource_service(
    storage: StorageService = Depends(_get_storage_service),
) -> ResourceService:
    return ResourceService(storage=storage)


@resource_router.get(
    "/contents/{content_id}/resources",
    summary="List resources for a content block",
    description=(
        "**Step 1 of 2** — Returns the lightweight list of resources linked to a "
        "content block.\n\n"
        "Use the returned `id` values to call "
        "`GET /resources/{id}/download-url` (**Step 2**) to obtain the access URL."
    ),
    tags=["Resources"],
)
async def list_content_resources(
    content_id: int,
    page: int = 1,
    page_size: int = 10,
    session: AsyncSession = Depends(get_db_session),
    _current_user: dict = Depends(get_current_approved_user),
    service: ResourceService = Depends(_get_resource_service),
):
    """List resources linked to a content block."""
    result = await service.list_resources(
        session=session, content_id=content_id, page=page, page_size=page_size
    )
    # Student-facing endpoint returns only the lightweight items list.
    return JSONResponse(content=result.get("items", []), status_code=status.HTTP_200_OK)


@resource_router.get(
    "/resources/{resource_id}/download-url",
    summary="Get download URL for a resource",
    description=(
        "**Step 2 of 2** — Returns the URL to access the material.\n\n"
        "- **External link** (`type = link`): returns the stored URL directly.\n"
        "- **Closed file** (`pdf`, `video`, etc.): generates a temporary presigned URL "
        "valid for 300 seconds."
    ),
    tags=["Resources"],
)
async def get_resource_download_url(
    resource_id: int,
    session: AsyncSession = Depends(get_db_session),
    _current_user: dict = Depends(get_current_approved_user),
    service: ResourceService = Depends(_get_resource_service),
):
    """Return the access URL for a resource."""
    result = await service.get_resource(session=session, resource_id=resource_id)
    if result is None:
        return JSONResponse(
            content={"detail": "Resource not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)
