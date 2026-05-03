"""Unit tests for StudentUploadService."""

import asyncio
import unittest
import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import tests.keys_test  # noqa: F401
from md_backend.services.student_upload_service import (
    ALLOWED_TYPES,
    MAX_FILE_SIZE,
    StudentUploadService,
)


class MockStorage:
    """Mock storage for tests."""

    async def upload_file(self, file_bytes, storage_key, content_type):
        """Return a fake URL."""
        return f"https://mock.storage/{storage_key}"


class TestValidateFile(unittest.TestCase):
    """Unit tests for StudentUploadService.validate_file."""

    def setUp(self):
        self.service = StudentUploadService(storage=MockStorage())

    def test_valid_file_returns_none(self):
        file = MagicMock()
        file.content_type = "application/pdf"
        file_bytes = b"x" * 1024  # 1KB
        self.assertIsNone(self.service.validate_file(file, file_bytes))

    def test_file_too_large_returns_error(self):
        file = MagicMock()
        file.content_type = "application/pdf"
        file_bytes = b"x" * (MAX_FILE_SIZE + 1)
        result = self.service.validate_file(file, file_bytes)
        self.assertIsNotNone(result)
        self.assertIn("too large", result)

    def test_invalid_type_returns_error(self):
        file = MagicMock()
        file.content_type = "application/exe"
        file_bytes = b"x" * 1024
        result = self.service.validate_file(file, file_bytes)
        self.assertIsNotNone(result)
        self.assertIn("not allowed", result)

    def test_all_allowed_types_pass(self):
        for mime_type in ALLOWED_TYPES:
            file = MagicMock()
            file.content_type = mime_type
            file_bytes = b"x" * 1024
            self.assertIsNone(self.service.validate_file(file, file_bytes))


class TestGetUploadById(unittest.TestCase):
    """Unit tests for StudentUploadService.get_upload_by_id."""

    def setUp(self):
        self.service = StudentUploadService(storage=MockStorage())

    def test_returns_none_when_upload_not_found(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            self.service.get_upload_by_id(
                upload_id=uuid.uuid4(),
                requester_id=str(uuid.uuid4()),
                session=mock_session,
            )
        )
        self.assertIsNone(result)

    def test_returns_forbidden_when_not_owner(self):
        student_id = uuid.uuid4()
        upload = MagicMock()
        upload.student_id = student_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = upload
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            self.service.get_upload_by_id(
                upload_id=uuid.uuid4(),
                requester_id=str(uuid.uuid4()),  # diferente do student_id
                session=mock_session,
                is_superadmin=False,
            )
        )
        self.assertEqual(result, "forbidden")

    def test_superadmin_can_access_any_upload(self):
        student_id = uuid.uuid4()
        upload = MagicMock()
        upload.id = uuid.uuid4()
        upload.student_id = student_id
        upload.file_name = "test.pdf"
        upload.file_url = "https://mock.storage/test.pdf"
        upload.file_type = "application/pdf"
        upload.file_size_bytes = 1024
        upload.created_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = upload
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            self.service.get_upload_by_id(
                upload_id=uuid.uuid4(),
                requester_id=str(uuid.uuid4()),  # diferente do student_id
                session=mock_session,
                is_superadmin=True,
            )
        )
        self.assertIsInstance(result, dict)
        self.assertNotIn("password", result)