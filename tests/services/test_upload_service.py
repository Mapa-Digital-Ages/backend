"""Unit tests for UploadService."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

import tests.keys_test  # noqa: F401
from md_backend.services.storage_service import StorageService
from md_backend.services.upload_service import (
    ALLOWED_TYPES,
    MAX_FILE_SIZE,
    UploadService,
    _detect_mime,
    _sanitize_filename,
)


class MockStorage(StorageService):
    """In-memory storage for unit tests."""

    def __init__(self):
        """Init in-memory blob map."""
        self.store: dict[uuid.UUID, bytes] = {}

    async def upload_file(self, upload_id, storage_key, file_bytes, content_type):
        self.store[upload_id] = file_bytes

    async def read_file(self, upload_id, storage_key):
        return self.store.get(upload_id)


class TestDetectMime(unittest.TestCase):
    """Unit tests for _detect_mime magic-bytes detection."""

    def test_jpeg_detected(self):
        self.assertEqual(_detect_mime(b"\xff\xd8\xff\xe0" + b"\x00" * 100), "image/jpeg")

    def test_png_detected(self):
        self.assertEqual(_detect_mime(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100), "image/png")

    def test_pdf_detected(self):
        self.assertEqual(_detect_mime(b"%PDF-1.4 fake content"), "application/pdf")

    def test_doc_detected(self):
        self.assertEqual(_detect_mime(b"\xd0\xcf\x11\xe0" + b"\x00" * 100), "application/msword")

    def test_docx_detected(self):
        self.assertEqual(
            _detect_mime(b"PK\x03\x04" + b"\x00" * 100),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_unknown_returns_none(self):
        self.assertIsNone(_detect_mime(b"unknown binary content"))

    def test_empty_bytes_returns_none(self):
        self.assertIsNone(_detect_mime(b""))

    def test_all_allowed_types_have_magic(self):
        magic_samples = {
            "image/jpeg": b"\xff\xd8\xff",
            "image/png": b"\x89PNG\r\n\x1a\n",
            "application/pdf": b"%PDF",
            "application/msword": b"\xd0\xcf\x11\xe0",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
                b"PK\x03\x04"
            ),
        }
        for mime_type in ALLOWED_TYPES:
            sample = magic_samples[mime_type] + b"\x00" * 32
            self.assertEqual(_detect_mime(sample), mime_type)


class TestSanitizeFilename(unittest.TestCase):
    """Unit tests for _sanitize_filename."""

    def test_strips_path_components(self):
        self.assertEqual(_sanitize_filename("../../etc/passwd"), "passwd")

    def test_strips_control_characters(self):
        self.assertEqual(_sanitize_filename("file\x00name.pdf"), "filename.pdf")

    def test_strips_double_quote(self):
        self.assertEqual(_sanitize_filename('file"name.pdf'), "filename.pdf")

    def test_strips_backslash(self):
        self.assertEqual(_sanitize_filename("file\\name.pdf"), "filename.pdf")

    def test_normal_name_unchanged(self):
        self.assertEqual(_sanitize_filename("report-2024.pdf"), "report-2024.pdf")

    def test_empty_result_becomes_upload(self):
        self.assertEqual(_sanitize_filename('\x00"\\'), "upload")

    def test_long_name_capped_at_255(self):
        long_name = "a" * 300 + ".pdf"
        result = _sanitize_filename(long_name)
        self.assertLessEqual(len(result), 255)


class TestGetUploadById(unittest.TestCase):
    """Unit tests for UploadService.get_upload_by_id."""

    def setUp(self):
        self.service = UploadService(storage=MockStorage())

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
                requester_id=str(uuid.uuid4()),
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
                requester_id=str(uuid.uuid4()),
                session=mock_session,
                is_superadmin=True,
            )
        )
        self.assertIsInstance(result, dict)
        self.assertNotIn("password", result)
        self.assertIn("download_url", result)
        self.assertEqual(result["download_url"], f"/uploads/{upload.id}/content")


class TestGetUploadContent(unittest.TestCase):
    """Unit tests for UploadService.get_upload_content."""

    def test_returns_bytes_for_owner(self):
        storage = MockStorage()
        service = UploadService(storage=storage)

        student_id = uuid.uuid4()
        upload = MagicMock()
        upload.id = uuid.uuid4()
        upload.student_id = student_id
        upload.storage_key = "some/key"

        storage.store[upload.id] = b"hello"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = upload
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            service.get_upload_content(
                upload_id=upload.id,
                requester_id=str(student_id),
                session=mock_session,
            )
        )
        self.assertIsInstance(result, tuple)
        returned_upload, content = result
        self.assertEqual(content, b"hello")
        self.assertIs(returned_upload, upload)

    def test_returns_forbidden_for_non_owner(self):
        storage = MockStorage()
        service = UploadService(storage=storage)

        upload = MagicMock()
        upload.id = uuid.uuid4()
        upload.student_id = uuid.uuid4()
        upload.storage_key = "some/key"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = upload
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            service.get_upload_content(
                upload_id=upload.id,
                requester_id=str(uuid.uuid4()),
                session=mock_session,
                is_superadmin=False,
            )
        )
        self.assertEqual(result, "forbidden")

    def test_returns_none_when_upload_not_found(self):
        service = UploadService(storage=MockStorage())

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            service.get_upload_content(
                upload_id=uuid.uuid4(),
                requester_id=str(uuid.uuid4()),
                session=mock_session,
            )
        )
        self.assertIsNone(result)
