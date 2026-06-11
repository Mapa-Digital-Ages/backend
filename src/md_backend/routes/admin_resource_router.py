"""Admin resource routes — metadata listing, detail, update, and delete."""

import json

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import ResourceCreateRequest, ResourceUpdateRequest
from md_backend.services.resource_service import ResourceService
from md_backend.services.storage_service import (
    PostgresBlobStorageService,
    S3StorageService,
    StorageService,
)
from md_backend.utils.database import get_db_session
from md_backend.utils.settings import settings

admin_resource_router = APIRouter()


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


@admin_resource_router.post(
    "",
    summary="Create a resource",
    description="Creates a metadata-only resource record linked to a content block.",
    tags=["Admin – Resources"],
)
async def create_resource(
    request: ResourceCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    service: ResourceService = Depends(_get_resource_service),
):
    """Create a metadata-only resource record linked to a content block."""
    from md_backend.models.db_models import Content, Resource

    content = await session.get(Content, request.content_id)
    if content is None:
        return JSONResponse(
            content={"detail": "Content not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    from md_backend.models.db_models import ResourceTypeEnum

    resource = Resource(
        content_id=request.content_id,
        type=ResourceTypeEnum(request.type),
        title=request.title,
        file_url=request.file_url,
    )
    session.add(resource)
    await session.commit()
    await session.refresh(resource)
    return Response(
        content=json.dumps(service._resource_to_dict(resource), default=str),
        media_type="application/json",
        status_code=status.HTTP_201_CREATED,
    )


@admin_resource_router.get(
    "",
    summary="List resources",
    description=(
        "Returns a paginated list of all resources.\n\n"
        "**Query parameters:**\n"
        "- `page` *(int, default 1)*: page number (1-based).\n"
        "- `page_size` *(int, default 10, max 100)*: items per page.\n"
        "- `content_id` *(int, optional)*: restrict results to a specific content block.\n"
        "- `query` *(str, optional)*: case-insensitive substring match on title."
    ),
    tags=["Admin – Resources"],
)
async def list_resources(
    session: AsyncSession = Depends(get_db_session),
    service: ResourceService = Depends(_get_resource_service),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    content_id: int | None = Query(default=None),
    query: str | None = Query(default=None),
):
    """List resources with optional filtering and pagination."""
    from sqlalchemy import func, select

    from md_backend.models.db_models import Resource

    stmt = select(Resource)
    if content_id is not None:
        stmt = stmt.where(Resource.content_id == content_id)
    if query:
        stmt = stmt.where(func.lower(Resource.title).like(f"%{query.strip().lower()}%"))

    import math

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(Resource.id.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await session.execute(stmt)).scalars().all()

    return Response(
        content=json.dumps(
            {
                "items": [service._resource_to_dict(r) for r in rows],
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": max(1, math.ceil(total / page_size)),
            },
            default=str,
        ),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )


@admin_resource_router.get(
    "/{resource_id}",
    summary="Get resource by ID",
    tags=["Admin – Resources"],
)
async def get_resource(
    resource_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: ResourceService = Depends(_get_resource_service),
):
    """Return full metadata for a single resource."""
    result = await service.get_resource(session=session, resource_id=resource_id)
    if result is None:
        return JSONResponse(
            content={"detail": "Resource not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return Response(
        content=json.dumps(result, default=str),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )


@admin_resource_router.patch(
    "/{resource_id}",
    summary="Update resource metadata",
    description=(
        "Updates **metadata-only** fields (`title`). "
        "Storage fields are never modified. "
        "To replace the file, delete and recreate the resource."
    ),
    tags=["Admin – Resources"],
)
async def update_resource(
    resource_id: int,
    request: ResourceUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    service: ResourceService = Depends(_get_resource_service),
):
    """Partially update a resource's metadata fields."""
    from md_backend.models.db_models import Resource

    resource = await session.get(Resource, resource_id)
    if resource is None:
        return JSONResponse(
            content={"detail": "Resource not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if request.title is not None:
        resource.title = request.title.strip()
    await session.commit()
    await session.refresh(resource)
    return Response(
        content=json.dumps(service._resource_to_dict(resource), default=str),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )


@admin_resource_router.delete(
    "/{resource_id}",
    summary="Delete a resource (hard delete)",
    description=(
        "Permanently deletes the resource record and its physical file from cloud storage.\n\n"
        "**⚠️ Irreversível.** Remove tanto o arquivo na nuvem quanto o registro no banco.\n\n"
        "O arquivo é removido do storage *antes* do registro do banco. "
        "Se o storage falhar, o registro é preservado e um `500` é retornado."
    ),
    tags=["Admin – Resources"],
)
async def delete_resource(
    resource_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: ResourceService = Depends(_get_resource_service),
):
    """Hard-delete a resource and its physical file from storage."""
    from md_backend.models.db_models import Resource

    resource = await session.get(Resource, resource_id)
    if resource is None:
        return JSONResponse(
            content={"detail": "Resource not found."},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    deleted = await service.delete_resource(session=session, resource_id=resource_id)
    if not deleted:
        return JSONResponse(
            content={"detail": "Storage deletion failed; database record preserved."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return JSONResponse(
        content={"detail": "Resource deleted successfully."},
        status_code=status.HTTP_200_OK,
    )
