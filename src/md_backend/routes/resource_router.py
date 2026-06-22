"""Admin routes for content resource management."""

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.services.resource_service import ResourceService
from md_backend.services.storage_service import (
    PostgresBlobStorageService,
    S3StorageService,
    StorageService,
)
from md_backend.utils.database import get_db_session
from md_backend.utils.security import get_current_approved_user, get_current_superadmin
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


@resource_router.post("/{content_id}/resources")
async def create_resource(
    content_id: int,
    file: UploadFile | None = File(default=None),
    title: str = Form(..., min_length=1),
    type: str = Form(
        ...,
        pattern=r"^(video|pdf|presentation|link|document)$",
        description="Resource type",
    ),
    url_or_contents: str = Form(default=""),
    session: AsyncSession = Depends(get_db_session),
    storage: StorageService = Depends(_get_storage_service),
    current_user: dict = Depends(get_current_superadmin),
):
    """Create and upload a resource for content.

    POST /admin/contents/{content_id}/resources

    ## Request Body (multipart/form-data)
    - **file** (File): The resource file (required for pdf, video, document, presentation)
    - **title** (str): Resource title (required, min_length=1)
    - **type** (str): Resource type - one of: video, pdf, presentation, link, document (required)
    - **url_or_contents** (str): URL for link type or additional content (required for link type)

    ## Validation Rules
    - If type='link': file must NOT be provided, url_or_contents is required
    - If type='pdf'|'video'|'document'|'presentation': file is required
    - Magic byte validation ensures file type matches declared type (security)
    - Size limits:
      - Documents/PDFs/Presentations: 50MB max
      - Videos: 500MB max

    ## Response
    - **201 Created**: Resource successfully uploaded with metadata
    - **400 Bad Request**: Validation error (invalid type, missing file, magic bytes mismatch)
    - **403 Forbidden**: User not authorized (must be superadmin)
    - **404 Not Found**: Content not found
    - **503 Service Unavailable**: Storage service error
    """
    # Validate type-specific requirements
    resource_type = type.lower().strip()

    if resource_type == "link":
        # For links, file should not be provided
        # Check if file was actually uploaded (not just empty placeholder)
        if file and file.filename:
            file_bytes = await file.read()
            if file_bytes:
                return JSONResponse(
                    content={"detail": "File should not be provided for link type resources"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            # Reset file pointer in case we need it elsewhere
            await file.seek(0)

        # Require url_or_contents for links
        if not url_or_contents or not url_or_contents.strip():
            return JSONResponse(
                content={"detail": "url_or_contents is required for link type resources"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        # For links, we create a resource without file upload
        service = ResourceService(storage=storage)
        result = await service.create_link_resource(
            session=session,
            content_id=content_id,
            title=title,
            url=url_or_contents.strip(),
        )
        if isinstance(result, str):
            if result == "invalid_content_id":
                return JSONResponse(
                    content={"detail": "Content not found"},
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            return JSONResponse(
                content={"detail": result},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)

    # For non-link types, file is required
    if not file or not getattr(file, "filename", None):
        return JSONResponse(
            content={"detail": "File is required for this resource type"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Read file bytes
    try:
        file_bytes = await file.read()
    except Exception:
        return JSONResponse(
            content={"detail": "Failed to read file"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not file_bytes:
        return JSONResponse(
            content={"detail": "File is required for this resource type"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Upload file resource
    service = ResourceService(storage=storage)
    result = await service.upload_resource(
        session=session,
        file_bytes=file_bytes,
        title=title,
        resource_type=resource_type,
        content_id=content_id,
        file_name=file.filename or title,
        file_type=file.content_type or "application/octet-stream",
    )

    if isinstance(result, str):
        # Map service errors to HTTP status codes
        error_code_map = {
            "invalid_content_id": (404, "Content not found"),
            "title_required": (400, "Title is required"),
            "invalid_file_type": (400, "Invalid file type"),
            "invalid_resource_type": (400, "Invalid resource type"),
            "invalid_file": (400, "File is empty"),
            "file_too_large": (400, "File size exceeds limit"),
            "invalid_file_format": (400, "File format is invalid or corrupted"),
            "file_type_mismatch": (
                400,
                "File content does not match declared type (magic bytes check failed)",
            ),
            "storage_error": (503, "Storage service error"),
        }

        status_code, detail = error_code_map.get(result, (400, result))
        return JSONResponse(
            content={"detail": detail},
            status_code=status_code,
        )

    return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)
