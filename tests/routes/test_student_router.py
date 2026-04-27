"""Tests for the student router."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from tests.helpers import get_admin_headers


class TestStudentRouterValidation(unittest.TestCase):
    """Unit tests: validação dos campos do StudentRequest."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.test_client)
        self.valid_payload = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@example.com",
            "password": "securepass123",
            "birth_date": "2010-05-20",
            "student_class": "5A",
        }

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_missing_first_name_returns_422(self):
        payload = {**self.valid_payload}
        del payload["first_name"]
        response = self.test_client.post("/students", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_missing_last_name_returns_422(self):
        payload = {**self.valid_payload}
        del payload["last_name"]
        response = self.test_client.post("/students", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_invalid_email_returns_422(self):
        payload = {**self.valid_payload, "email": "not-an-email"}
        response = self.test_client.post("/students", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_password_too_short_returns_422(self):
        payload = {**self.valid_payload, "password": "123"}
        response = self.test_client.post("/students", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_invalid_birth_date_returns_422(self):
        payload = {**self.valid_payload, "birth_date": "not-a-date"}
        response = self.test_client.post("/students", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_missing_student_class_returns_422(self):
        payload = {**self.valid_payload}
        del payload["student_class"]
        response = self.test_client.post("/students", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)


class TestStudentRouterIntegration(unittest.TestCase):
    """Integration tests: fluxo completo do POST /students."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.test_client)
        self.valid_payload = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "student.create@example.com",
            "password": "securepass123",
            "birth_date": "2010-05-20",
            "student_class": "5A",
        }

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_create_student_success_returns_201(self):
        response = self.test_client.post(
            "/students", json=self.valid_payload, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["first_name"], "John")
        self.assertEqual(data["last_name"], "Doe")
        self.assertEqual(data["email"], "student.create@example.com")
        self.assertEqual(data["student_class"], "5A")
        self.assertNotIn("password", data)
        self.assertIn("id", data)
        self.assertIn("user_id", data)

    def test_duplicate_email_returns_409(self):
        self.test_client.post("/students", json=self.valid_payload, headers=self.admin_headers)
        response = self.test_client.post(
            "/students", json=self.valid_payload, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Email already registered"})

    def test_unauthenticated_returns_401(self):
        response = self.test_client.post("/students", json=self.valid_payload)
        self.assertEqual(response.status_code, 401)

    def test_rollback_on_student_profile_failure(self):
        """Simula falha no StudentProfile e verifica rollback do user_profile."""
        email = "rollback.test@example.com"
        payload = {**self.valid_payload, "email": email}

        with patch(
            "md_backend.services.student_service.StudentProfile",
            side_effect=Exception("Simulated DB failure"),
        ):
            self.test_client.post("/students", json=payload, headers=self.admin_headers)

        # Se houve rollback, deve conseguir criar com o mesmo email
        response = self.test_client.post("/students", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 201)
