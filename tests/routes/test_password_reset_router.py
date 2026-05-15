"""Tests for password reset routes."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from tests.helpers import create_approved_user, get_admin_headers

_KNOWN_CODE = "654321"


class TestPasswordResetRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.test_client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_request_reset_returns_detail_for_existing_user(self):
        create_approved_user(self.test_client, self.admin_headers, "reset_req@test.com")

        response = self.test_client.post(
            "/api/password-reset/request", json={"email": "reset_req@test.com"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["detail"], "Password reset code generated")
        self.assertNotIn("reset_code", data)

    def test_request_reset_uses_same_shape_for_unknown_email(self):
        response = self.test_client.post(
            "/api/password-reset/request", json={"email": "missing_reset@test.com"}
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["detail"], "Password reset code generated")
        self.assertNotIn("reset_code", data)

    def test_confirm_reset_updates_password_and_consumes_code(self):
        create_approved_user(
            self.test_client,
            self.admin_headers,
            "reset_confirm@test.com",
            password="oldpass123",
        )

        with patch(
            "md_backend.services.password_reset_service._generate_reset_code",
            return_value=_KNOWN_CODE,
        ):
            self.test_client.post(
                "/api/password-reset/request", json={"email": "reset_confirm@test.com"}
            )

        response = self.test_client.post(
            "/api/password-reset/confirm",
            json={
                "email": "reset_confirm@test.com",
                "code": _KNOWN_CODE,
                "new_password": "newpass123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"detail": "Password reset completed"})

        old_login = self.test_client.post(
            "/api/login", json={"email": "reset_confirm@test.com", "password": "oldpass123"}
        )
        self.assertEqual(old_login.status_code, 401)

        new_login = self.test_client.post(
            "/api/login", json={"email": "reset_confirm@test.com", "password": "newpass123"}
        )
        self.assertEqual(new_login.status_code, 200)

        reused_response = self.test_client.post(
            "/api/password-reset/confirm",
            json={
                "email": "reset_confirm@test.com",
                "code": _KNOWN_CODE,
                "new_password": "anotherpass123",
            },
        )
        self.assertEqual(reused_response.status_code, 400)
        self.assertEqual(reused_response.json(), {"detail": "Invalid or expired reset code"})

    def test_confirm_reset_rejects_invalid_code(self):
        create_approved_user(self.test_client, self.admin_headers, "reset_invalid@test.com")

        response = self.test_client.post(
            "/api/password-reset/confirm",
            json={
                "email": "reset_invalid@test.com",
                "code": "000000",
                "new_password": "newpass123",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Invalid or expired reset code"})

    def test_confirm_reset_validates_payload(self):
        response = self.test_client.post(
            "/api/password-reset/confirm",
            json={
                "email": "not-an-email",
                "code": "123",
                "new_password": "short",
            },
        )

        self.assertEqual(response.status_code, 422)
