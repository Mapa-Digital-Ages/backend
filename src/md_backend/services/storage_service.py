"""Storage service interface and implementations."""

import uuid
from abc import ABC, abstractmethod

import aioboto3
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import StudentUploadBlob


class StorageService(ABC):
    """Abstract base class for file storage backends.

    The interface accepts both ``upload_id`` and ``storage_key`` so concrete
    backends (Postgres, S3, ...) are interchangeable without caller changes.
    """

    @abstractmethod
    async def upload_file(
        self,
        upload_id: uuid.UUID,
        storage_key: str,
        file_bytes: bytes,
        content_type: str,
    ) -> None:
        """Persist file bytes for the given upload."""
        ...

    @abstractmethod
    async def read_file(
        self,
        upload_id: uuid.UUID,
        storage_key: str,
    ) -> bytes | None:
        """Retrieve file bytes for the given upload, or None if missing."""
        ...


class PostgresBlobStorageService(StorageService):
    """Stores file bytes in a dedicated Postgres BYTEA table.

    Uses ``upload_id`` as the lookup key; ``storage_key`` is ignored here but
    kept in the signature so the S3 backend (which needs it) is a drop-in.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with an async DB session."""
        self.session = session

    async def upload_file(
        self,
        upload_id: uuid.UUID,
        storage_key: str,
        file_bytes: bytes,
        content_type: str,
    ) -> None:
        """Insert a blob row; the surrounding session must commit."""
        self.session.add(StudentUploadBlob(upload_id=upload_id, content=file_bytes))

    async def read_file(
        self,
        upload_id: uuid.UUID,
        storage_key: str,
    ) -> bytes | None:
        """Fetch the blob bytes for the upload."""
        result = await self.session.execute(
            select(StudentUploadBlob.content).where(StudentUploadBlob.upload_id == upload_id)
        )
        return result.scalar_one_or_none()


class S3StorageService(StorageService):
    """S3-compatible storage backend using aioboto3.

    Works with AWS S3 and S3-compatible endpoints (MinIO, LocalStack).
    Set ``endpoint_url`` to target a non-AWS endpoint.
    """

    def __init__(
        self,
        bucket: str,
        region: str,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        """Initialize with bucket + region; credentials default to environment/IAM role."""
        self.bucket = bucket
        self.region = region
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.endpoint_url = endpoint_url

    def _client(self):
        """Return a configured aioboto3 S3 client context manager."""
        session = aioboto3.Session(
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
        )
        return session.client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
        )

    async def upload_file(
        self,
        upload_id: uuid.UUID,
        storage_key: str,
        file_bytes: bytes,
        content_type: str,
    ) -> None:
        """Upload bytes to S3 under ``storage_key``."""
        async with self._client() as s3:  # type: ignore[attr-defined]
            await s3.put_object(
                Bucket=self.bucket,
                Key=storage_key,
                Body=file_bytes,
                ContentType=content_type,
            )

    async def read_file(
        self,
        upload_id: uuid.UUID,
        storage_key: str,
    ) -> bytes | None:
        """Download bytes from S3 by ``storage_key``. Returns None if not found."""
        async with self._client() as s3:  # type: ignore[attr-defined]
            try:
                response = await s3.get_object(Bucket=self.bucket, Key=storage_key)
                return await response["Body"].read()
            except Exception:
                return None
