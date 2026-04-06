"""Tests for the login router."""

import unittest

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app


class TestLoginRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()
        self.test_client.post(
            "/register", json={"email": "login@test.com", "password": "validpass123"}
        )

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_login_success(self):
        response = self.test_client.post(
            "/login", json={"email": "login@test.com", "password": "validpass123"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["token_type"], "bearer")

    def test_login_wrong_password(self):
        response = self.test_client.post(
            "/login", json={"email": "login@test.com", "password": "wrongpassword"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Credenciais inválidas"})

    def test_login_nonexistent_user(self):
        response = self.test_client.post(
            "/login", json={"email": "ghost@test.com", "password": "validpass123"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Credenciais inválidas"})

    def test_login_invalid_email(self):
        response = self.test_client.post(
            "/login", json={"email": "not-an-email", "password": "validpass123"}
        )
        self.assertEqual(response.status_code, 422)
