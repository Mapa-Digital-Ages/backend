"""Admin resource routes — metadata listing, detail, and update."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import ResourceUpdateRequest
from md_backend.services.resource_service import ResourceService
from md_backend.services.storage_service import (
    PostgresBlobStorageService,
    S3StorageService,
    StorageService,
)
from md_backend.utils.database import get_db_session
from md_backend.utils.settings import settings

admin_resource_router = APIRouter()
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


@admin_resource_router.get(
    "",
    summary="List resources",
    description=(
        "Returns a paginated list of all resources. "
        "Use the query parameters below to filter and paginate results.\n\n"
        "**Query parameters:**\n"
        "- `page` *(int, default 1)*: page number (1-based).\n"
        "- `page_size` *(int, default 10, max 100)*: items per page.\n"
        "- `content_id` *(int, optional)*: restrict results to a specific content block.\n"
        "- `query` *(str, optional)*: case-insensitive substring match against the resource title."
        "**Note:** this endpoint only returns metadata; binary files are never transferred here."
    ),
    tags=["Admin – Resources"],
)
async def list_resources(
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(default=1, ge=1, description="Page number (1-based)."),
    page_size: int = Query(default=10, ge=1, le=100, description="Items per page (max 100)."),
    content_id: int | None = Query(default=None, description="Filter by content block ID."),
    query: str | None = Query(default=None, description="Case-insensitive title search."),
):
    """List resources with optional filtering. Restricted to administrators."""
    result = await _resource_service.list_resources(
        session=session,
        page=page,
        page_size=page_size,
        content_id=content_id,
        query=query,
    )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@admin_resource_router.get(
    "/{resource_id}",
    summary="Get resource by ID",
    description="Returns the full metadata detail for a single resource.",
    tags=["Admin – Resources"],
)
async def get_resource(
    resource_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Fetch a single resource record. Restricted to administrators."""
    result = await _resource_service.get_resource(session=session, resource_id=resource_id)
    if result is None:
        return JSONResponse(
            content={"detail": "Resource not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@admin_resource_router.patch(
    "/{resource_id}",
    summary="Update resource metadata",
    description=(
        "Updates **metadata-only** fields of a resource (currently: `title`).\n\n"
        "**Important constraints:**\n"
        "- Binary file fields (`storage_key`, `file_url`, `file_name`, `file_type`, "
        "`file_size_bytes`) are **never modified** by this endpoint.\n"
        "- To replace the physical file, delete the resource and create a new one "
        "through the upload endpoint.\n\n"
        "Restricted to administrators."
    ),
    tags=["Admin – Resources"],
)
async def update_resource(
    resource_id: int,
    request: ResourceUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Partially update a resource's metadata. Restricted to administrators."""
    result = await _resource_service.update_resource(
        session=session,
        resource_id=resource_id,
        title=request.title,
    )
    if result is None:
        return JSONResponse(
            content={"detail": "Resource not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return JSONResponse(content=result, status_code=status.HTTP_200_OK)


@admin_resource_router.delete(
    "/{resource_id}",
    summary="Delete a resource (hard delete)",
    description=(
        "Permanently deletes a resource record and its associated physical file from "
        "cloud storage.\n\n"
        "**⚠️ This operation is irreversible.** Both the metadata row in the database "
        "and the file stored on the cloud provider are permanently removed. "
        "There is no soft-delete or recycle bin.\n\n"
        "**Deletion order guarantee:** the physical file is removed from cloud storage "
        "*before* the database row is deleted. If the storage provider returns an error, "
        "the database row is preserved and a `500` is returned — preventing orphaned files "
        "in the cloud.\n\n"
        "- External links (`type = link`) have no physical file; only the DB row is removed.\n"
        "- Restricted to administrators."
    ),
    tags=["Admin – Resources"],
)
async def delete_resource(
    resource_id: int,
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(_get_storage_service),
):
    """Hard-delete a resource. Restricted to administrators."""
    result = await _resource_service.delete_resource(
        session=session,
        resource_id=resource_id,
        storage=storage,
    )

    match result["status"]:
        case "deleted":
            return JSONResponse(
                content={"detail": "Resource deleted successfully."},
                status_code=status.HTTP_200_OK,
            )
        case "not_found":
            return JSONResponse(
                content={"detail": "Resource not found."},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        case "storage_error":
            return JSONResponse(
                content={
                    "detail": "Storage deletion failed. Database record preserved.",
                    "storage_error": result.get("detail"),
                },
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        case _:
            raise HTTPException(status_code=500, detail="Unexpected error.")
