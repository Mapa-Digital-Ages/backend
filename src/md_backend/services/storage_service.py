"""Storage service interface and implementations."""

import uuid
from abc import ABC, abstractmethod

import aioboto3
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from helper_backend.utils.logger import get_logger
from md_backend.models.db_models import StudentUploadBlob

logger = get_logger(__name__)
_logger_extra = {"component_name": "storage_service","component_version": "v1",}


class StorageService(ABC):
    """Abstract base class for file storage backends."""

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
        """Retrieve file bytes for the given upload."""
        ...


class PostgresBlobStorageService(StorageService):
    """Stores file bytes in a dedicated Postgres BYTEA table."""

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
        """Insert a blob row."""

        logger.info(
            "Uploading file to Postgres storage",
            extra={
                **_logger_extra,
                "upload_id": str(upload_id),
                "storage_key": storage_key,
                "content_type": content_type,
                "file_size": len(file_bytes),
            },
        )

        self.session.add(
            StudentUploadBlob(
                upload_id=upload_id,
                content=file_bytes,
            )
        )

    async def read_file(
        self,
        upload_id: uuid.UUID,
        storage_key: str,
    ) -> bytes | None:
        """Fetch blob bytes for the upload."""

        logger.info(
            "Reading file from Postgres storage",
            extra={
                **_logger_extra,
                "upload_id": str(upload_id),
                "storage_key": storage_key,
            },
        )

        result = await self.session.execute(
            select(StudentUploadBlob.content).where(
                StudentUploadBlob.upload_id == upload_id
            )
        )

        blob = result.scalar_one_or_none()

        if blob is None:
            logger.warning(
                "File not found in Postgres storage",
                extra={
                    **_logger_extra,
                    "upload_id": str(upload_id),
                    "storage_key": storage_key,
                },
            )

            return None

        logger.info(
            "File read successfully from Postgres storage",
            extra={
                **_logger_extra,
                "upload_id": str(upload_id),
                "storage_key": storage_key,
            },
        )

        return blob


class S3StorageService(StorageService):
    """S3-compatible storage backend using aioboto3."""

    def __init__(
        self,
        bucket: str,
        region: str,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        """Initialize S3 storage service."""

        self.bucket = bucket
        self.region = region
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.endpoint_url = endpoint_url

    def _client(self):
        """Return configured aioboto3 S3 client."""

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
        """Upload bytes to S3."""

        logger.info(
            "Uploading file to S3 storage",
            extra={
                **_logger_extra,
                "upload_id": str(upload_id),
                "storage_key": storage_key,
                "bucket": self.bucket,
                "content_type": content_type,
                "file_size": len(file_bytes),
            },
        )

        async with self._client() as s3:  # type: ignore[attr-defined]
            await s3.put_object(
                Bucket=self.bucket,
                Key=storage_key,
                Body=file_bytes,
                ContentType=content_type,
            )

        logger.info(
            "File uploaded successfully to S3",
            extra={
                **_logger_extra,
                "upload_id": str(upload_id),
                "storage_key": storage_key,
                "bucket": self.bucket,
            },
        )

    async def read_file(
        self,
        upload_id: uuid.UUID,
        storage_key: str,
    ) -> bytes | None:
        """Download bytes from S3."""

        logger.info(
            "Reading file from S3 storage",
            extra={
                **_logger_extra,
                "upload_id": str(upload_id),
                "storage_key": storage_key,
                "bucket": self.bucket,
            },
        )

        async with self._client() as s3:  # type: ignore[attr-defined]
            try:
                response = await s3.get_object(
                    Bucket=self.bucket,
                    Key=storage_key,
                )

                content = await response["Body"].read()

                logger.info(
                    "File read successfully from S3",
                    extra={
                        **_logger_extra,
                        "upload_id": str(upload_id),
                        "storage_key": storage_key,
                        "bucket": self.bucket,
                    },
                )

                return content

            except Exception as error:
                logger.exception(
                    "Failed to read file from S3",
                    extra={
                        **_logger_extra,
                        "upload_id": str(upload_id),
                        "storage_key": storage_key,
                        "bucket": self.bucket,
                        "error": str(error),
                    },
                )

                return None