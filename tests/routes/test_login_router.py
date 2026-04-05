"""Tests for the login router."""

import unittest

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app


class TestLoginRouter(unittest.TestCase):
    def setUp(self):
        """Setup method to initialize the TestClient."""
        self.test_client = TestClient(app, raise_server_exceptions=False)

    def test_login_success(self):
        """Test login with valid credentials."""
        response = self.test_client.post(
            "/login", json={"email": "admin@test.com", "password": "secret"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"detail": "Login successful!"})

    def test_login_invalid_credentials(self):
        """Test login with wrong credentials."""
        response = self.test_client.post(
            "/login", json={"email": "errado@test.com", "password": "errado"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Credenciais inválidas."})
