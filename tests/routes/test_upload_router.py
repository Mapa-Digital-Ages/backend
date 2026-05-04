"""Integration tests for student upload endpoints."""

import io
import unittest
import uuid

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from tests.helpers import get_admin_headers


def _make_student(test_client, admin_headers):
    """Helper: create a student and return their user_id."""
    payload = {
        "first_name": "Upload",
        "last_name": "Student",
        "email": f"upload.student.{uuid.uuid4()}@example.com",
        "password": "securepass123",
        "birth_date": "2010-05-20",
        "student_class": "5th class",
    }
    resp = test_client.post("/api/student", json=payload, headers=admin_headers)
    return resp.json()["user_id"]


def _make_upload(test_client, admin_headers, student_id, content=b"%PDF-1.4 fake pdf content"):
    """Helper: upload a file for a student and return the response."""
    return test_client.post(
        f"/api/student/{student_id}/uploads",
        files={"file": ("test.pdf", io.BytesIO(content), "application/pdf")},
        headers=admin_headers,
    )


class TestStudentUploadPost(unittest.TestCase):
    """Integration tests for POST /student/{student_id}/uploads."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.test_client)
        self.student_id = _make_student(self.test_client, self.admin_headers)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_upload_success_returns_201(self):
        response = _make_upload(self.test_client, self.admin_headers, self.student_id)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("id", data)
        self.assertIn("download_url", data)
        self.assertIn("file_name", data)
        self.assertNotIn("password", data)
        self.assertEqual(data["download_url"], f"/uploads/{data['id']}/content")

    def test_upload_nonexistent_student_returns_404(self):
        response = _make_upload(self.test_client, self.admin_headers, str(uuid.uuid4()))
        self.assertEqual(response.status_code, 404)

    def test_upload_too_large_returns_400(self):
        large_content = b"x" * (10 * 1024 * 1024 + 1)
        response = self.test_client.post(
            f"/api/student/{self.student_id}/uploads",
            files={"file": ("big.pdf", io.BytesIO(large_content), "application/pdf")},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_upload_invalid_type_returns_400(self):
        response = self.test_client.post(
            f"/api/student/{self.student_id}/uploads",
            files={"file": ("malware.exe", io.BytesIO(b"bad"), "application/exe")},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_upload_unauthenticated_returns_401(self):
        response = self.test_client.post(
            f"/api/student/{self.student_id}/uploads",
            files={"file": ("test.pdf", io.BytesIO(b"content"), "application/pdf")},
        )
        self.assertEqual(response.status_code, 401)


class TestStudentUploadGet(unittest.TestCase):
    """Integration tests for GET /student/{student_id}/uploads and GET /uploads/{id}."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.test_client)
        self.student_id = _make_student(self.test_client, self.admin_headers)
        upload_resp = _make_upload(self.test_client, self.admin_headers, self.student_id)
        self.upload = upload_resp.json()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_list_uploads_returns_200(self):
        response = self.test_client.get(
            f"/api/student/{self.student_id}/uploads",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_list_uploads_pagination(self):
        response = self.test_client.get(
            f"/api/student/{self.student_id}/uploads",
            params={"page": 1, "size": 1},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(response.json()), 1)

    def test_list_uploads_nonexistent_student_returns_404(self):
        response = self.test_client.get(
            f"/api/student/{uuid.uuid4()}/uploads",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 404)

    def test_get_upload_by_id_success(self):
        upload_id = self.upload["id"]
        response = self.test_client.get(
            f"/api/uploads/{upload_id}",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], upload_id)
        self.assertEqual(data["download_url"], f"/uploads/{upload_id}/content")
        self.assertNotIn("password", data)

    def test_get_upload_by_id_not_found(self):
        response = self.test_client.get(
            f"/api/uploads/{uuid.uuid4()}",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 404)

    def test_get_upload_another_student_as_admin(self):
        other_student_id = _make_student(self.test_client, self.admin_headers)
        other_upload = _make_upload(self.test_client, self.admin_headers, other_student_id).json()

        response = self.test_client.get(
            f"/api/uploads/{other_upload['id']}",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)

    def test_list_uploads_unauthenticated_returns_401(self):
        response = self.test_client.get(f"/api/student/{self.student_id}/uploads")
        self.assertEqual(response.status_code, 401)


class TestStudentUploadDownload(unittest.TestCase):
    """Integration tests for GET /uploads/{id}/content."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.test_client)
        self.student_id = _make_student(self.test_client, self.admin_headers)
        self.uploaded_bytes = b"%PDF-1.4 round-trip-test-content"
        upload_resp = _make_upload(
            self.test_client, self.admin_headers, self.student_id, content=self.uploaded_bytes
        )
        self.upload = upload_resp.json()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_download_returns_original_bytes(self):
        response = self.test_client.get(
            f"/api/uploads/{self.upload['id']}/content",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.uploaded_bytes)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("test.pdf", response.headers["content-disposition"])

    def test_download_unknown_id_returns_404(self):
        response = self.test_client.get(
            f"/api/uploads/{uuid.uuid4()}/content",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 404)

    def test_download_unauthenticated_returns_401(self):
        response = self.test_client.get(f"/api/uploads/{self.upload['id']}/content")
        self.assertEqual(response.status_code, 401)
