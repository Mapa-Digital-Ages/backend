"""Unit tests for UploadService."""

import asyncio
import io
import unittest
import uuid
import zipfile
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


def _make_docx_bytes() -> bytes:
    """Minimal in-memory ZIP with [Content_Types].xml — passes DOCX magic check."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


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
            _detect_mime(_make_docx_bytes()),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_docx_zip_without_content_types_returns_none(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", "<document/>")
        self.assertIsNone(_detect_mime(buf.getvalue()))

    def test_unknown_returns_none(self):
        self.assertIsNone(_detect_mime(b"unknown binary content"))

    def test_empty_bytes_returns_none(self):
        self.assertIsNone(_detect_mime(b""))

    def test_all_allowed_types_have_magic(self):
        magic_samples = {
            "image/jpeg": b"\xff\xd8\xff" + b"\x00" * 32,
            "image/png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
            "application/pdf": b"%PDF" + b"\x00" * 32,
            "application/msword": b"\xd0\xcf\x11\xe0" + b"\x00" * 32,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
                _make_docx_bytes()
            ),
        }
        for mime_type in ALLOWED_TYPES:
            self.assertEqual(_detect_mime(magic_samples[mime_type]), mime_type)


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

        # First execute → upload found; second execute (guardian_owns_student) → no link
        found_result = MagicMock()
        found_result.scalar_one_or_none.return_value = upload
        no_link_result = MagicMock()
        no_link_result.scalar_one_or_none.return_value = None
        mock_session = AsyncMock()
        mock_session.execute.side_effect = [found_result, no_link_result]

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
        assert isinstance(result, dict)
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
        assert isinstance(result, tuple)
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

        # First execute → upload found; second (guardian_owns_student) → no link
        found_result = MagicMock()
        found_result.scalar_one_or_none.return_value = upload
        no_link_result = MagicMock()
        no_link_result.scalar_one_or_none.return_value = None
        mock_session = AsyncMock()
        mock_session.execute.side_effect = [found_result, no_link_result]

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

    def test_returns_none_when_storage_has_no_bytes(self):
        """Upload metadata exists but storage returns None for the bytes."""

        class EmptyStorage(StorageService):
            async def upload_file(self, upload_id, storage_key, file_bytes, content_type):
                return None

            async def read_file(self, upload_id, storage_key):
                return None

        service = UploadService(storage=EmptyStorage())

        upload = MagicMock()
        upload.id = uuid.uuid4()
        upload.student_id = uuid.uuid4()
        upload.storage_key = "missing/key"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = upload
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            service.get_upload_content(
                upload_id=upload.id,
                requester_id=str(uuid.uuid4()),
                session=mock_session,
                is_superadmin=True,
            )
        )
        self.assertIsNone(result)


class TestDocxBadZipBranch(unittest.TestCase):
    """Cover the BadZipFile branch in _detect_mime."""

    def test_zip_magic_with_invalid_data_returns_none(self):
        # PK\x03\x04 magic header followed by garbage triggers zipfile.BadZipFile.
        bad = b"PK\x03\x04" + b"\x00" * 32
        self.assertIsNone(_detect_mime(bad))


class TestUploadStudentFileMissingFilename(unittest.TestCase):
    """Cover the empty-filename guard in upload_student_file."""

    def test_returns_error_when_filename_is_missing(self):
        service = UploadService(storage=MockStorage())

        # Student lookup → exists
        student = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = student
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        upload_file = MagicMock()
        upload_file.filename = ""

        result = asyncio.run(
            service.upload_student_file(
                student_id=uuid.uuid4(),
                file=upload_file,
                session=mock_session,
            )
        )
        self.assertEqual(result, "File name is required.")

    def test_returns_400_string_when_too_large(self):
        """Drives the >MAX_FILE_SIZE path so we exercise the chunked read loop."""
        service = UploadService(storage=MockStorage())

        student = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = student
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        big_chunks = [b"x" * (MAX_FILE_SIZE + 1), b""]

        upload_file = MagicMock()
        upload_file.filename = "big.pdf"
        upload_file.read = AsyncMock(side_effect=big_chunks)

        result = asyncio.run(
            service.upload_student_file(
                student_id=uuid.uuid4(),
                file=upload_file,
                session=mock_session,
            )
        )
        self.assertEqual(result, "File too large. Maximum size is 10MB.")


class TestCanAccessNonUuidRequester(unittest.TestCase):
    """Cover the ValueError branch in UploadService._can_access."""

    def test_non_uuid_requester_returns_false(self):
        service = UploadService(storage=MockStorage())

        upload = MagicMock()
        upload.student_id = uuid.uuid4()

        result = asyncio.run(
            service._can_access(
                upload=upload,
                requester_id="not-a-uuid",
                session=AsyncMock(),
                is_superadmin=False,
            )
        )
        self.assertFalse(result)
