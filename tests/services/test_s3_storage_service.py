"""Integration tests for S3StorageService against a real MinIO endpoint.

These tests are skipped unless AWS_S3_ENDPOINT_URL is set in the environment,
which is the case during CI (MinIO service) and local dev with MinIO running.
"""

import asyncio
import os
import unittest
import uuid

import tests.keys_test  # noqa: F401

MINIO_URL = os.getenv("AWS_S3_ENDPOINT_URL")
S3_BUCKET = os.getenv("AWS_S3_BUCKET", "test-bucket")
S3_REGION = os.getenv("AWS_S3_REGION", "us-east-1")
S3_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
S3_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin")


@unittest.skipUnless(MINIO_URL, "MinIO not configured — set AWS_S3_ENDPOINT_URL to run S3 tests")
class TestS3StorageService(unittest.TestCase):
    """Tests for S3StorageService using a MinIO backend."""

    def _make_service(self):
        from md_backend.services.storage_service import S3StorageService

        return S3StorageService(
            bucket=S3_BUCKET,
            region=S3_REGION,
            access_key_id=S3_ACCESS_KEY,
            secret_access_key=S3_SECRET_KEY,
            endpoint_url=MINIO_URL,
        )

    def test_upload_and_read_roundtrip(self):
        service = self._make_service()
        upload_id = uuid.uuid4()
        key = f"test/{upload_id}.pdf"
        data = b"%PDF test content"

        async def run():
            await service.upload_file(
                upload_id=upload_id,
                storage_key=key,
                file_bytes=data,
                content_type="application/pdf",
            )
            result = await service.read_file(upload_id=upload_id, storage_key=key)
            return result

        result = asyncio.run(run())
        self.assertEqual(result, data)

    def test_read_missing_key_returns_none(self):
        service = self._make_service()
        upload_id = uuid.uuid4()

        async def run():
            return await service.read_file(
                upload_id=upload_id,
                storage_key=f"nonexistent/{upload_id}.pdf",
            )

        result = asyncio.run(run())
        self.assertIsNone(result)

    def test_upload_overwrite_returns_latest(self):
        service = self._make_service()
        upload_id = uuid.uuid4()
        key = f"test/overwrite/{upload_id}.pdf"

        async def run():
            await service.upload_file(
                upload_id=upload_id,
                storage_key=key,
                file_bytes=b"original",
                content_type="application/pdf",
            )
            await service.upload_file(
                upload_id=upload_id,
                storage_key=key,
                file_bytes=b"updated",
                content_type="application/pdf",
            )
            return await service.read_file(upload_id=upload_id, storage_key=key)

        result = asyncio.run(run())
        self.assertEqual(result, b"updated")
