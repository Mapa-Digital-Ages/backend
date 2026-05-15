"""Unit tests for storage_service.S3StorageService."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import tests.keys_test  # noqa: F401
from md_backend.services.storage_service import S3StorageService


def _make_async_cm(client):
    """Wrap an object as an async context manager that yields it."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


class TestS3StorageServiceInit(unittest.TestCase):
    def test_stores_constructor_arguments(self):
        svc = S3StorageService(
            bucket="my-bucket",
            region="us-east-2",
            access_key_id="ak",
            secret_access_key="sk",
            endpoint_url="https://s3.example.com",
        )
        self.assertEqual(svc.bucket, "my-bucket")
        self.assertEqual(svc.region, "us-east-2")
        self.assertEqual(svc.access_key_id, "ak")
        self.assertEqual(svc.secret_access_key, "sk")
        self.assertEqual(svc.endpoint_url, "https://s3.example.com")


class TestS3StorageServiceClient(unittest.TestCase):
    def test_client_uses_aioboto3_session_with_credentials(self):
        svc = S3StorageService(
            bucket="b",
            region="us-east-1",
            access_key_id="ak",
            secret_access_key="sk",
            endpoint_url="https://s3.example.com",
        )
        fake_session = MagicMock()
        fake_session.client.return_value = "FAKE_CLIENT_CTX"

        with patch(
            "md_backend.services.storage_service.aioboto3.Session",
            return_value=fake_session,
        ) as session_cls:
            result = svc._client()

        session_cls.assert_called_once_with(
            aws_access_key_id="ak",
            aws_secret_access_key="sk",
        )
        fake_session.client.assert_called_once_with(
            "s3",
            region_name="us-east-1",
            endpoint_url="https://s3.example.com",
        )
        self.assertEqual(result, "FAKE_CLIENT_CTX")


class TestS3StorageServiceUpload(unittest.TestCase):
    def test_upload_file_calls_put_object(self):
        svc = S3StorageService(bucket="b", region="us-east-1")
        client = AsyncMock()
        client.put_object = AsyncMock()

        with patch.object(svc, "_client", return_value=_make_async_cm(client)):
            asyncio.run(
                svc.upload_file(
                    upload_id=uuid.uuid4(),
                    storage_key="students/1/file.pdf",
                    file_bytes=b"data",
                    content_type="application/pdf",
                )
            )

        client.put_object.assert_awaited_once_with(
            Bucket="b",
            Key="students/1/file.pdf",
            Body=b"data",
            ContentType="application/pdf",
        )


class TestS3StorageServiceRead(unittest.TestCase):
    def test_read_file_returns_bytes(self):
        svc = S3StorageService(bucket="b", region="us-east-1")

        body = MagicMock()
        body.read = AsyncMock(return_value=b"hello")
        client = MagicMock()
        client.get_object = AsyncMock(return_value={"Body": body})

        with patch.object(svc, "_client", return_value=_make_async_cm(client)):
            result = asyncio.run(
                svc.read_file(
                    upload_id=uuid.uuid4(),
                    storage_key="students/1/file.pdf",
                )
            )

        self.assertEqual(result, b"hello")

    def test_read_file_returns_none_on_exception(self):
        svc = S3StorageService(bucket="b", region="us-east-1")

        client = MagicMock()
        client.get_object = AsyncMock(side_effect=RuntimeError("missing"))

        with patch.object(svc, "_client", return_value=_make_async_cm(client)):
            result = asyncio.run(
                svc.read_file(
                    upload_id=uuid.uuid4(),
                    storage_key="students/1/missing.pdf",
                )
            )

        self.assertIsNone(result)
