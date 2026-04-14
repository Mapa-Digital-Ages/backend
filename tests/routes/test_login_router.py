"""Tests for the login router."""

import unittest

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from tests.helpers import create_approved_user, get_admin_headers


class TestLoginRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.test_client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_login_success_approved_user(self):
        create_approved_user(self.test_client, self.admin_headers, "login_ok@test.com")
        response = self.test_client.post(
            "/login", json={"email": "login_ok@test.com", "password": "validpass123"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("token", data)
        self.assertIn("role", data)
        self.assertIn("email", data)
        self.assertIn("name", data)

    def test_login_aguardando_user(self):
        self.test_client.post(
            "/register",
            json={"email": "waiting_lg@test.com", "password": "validpass123", "name": "Wait"},
        )
        response = self.test_client.post(
            "/login", json={"email": "waiting_lg@test.com", "password": "validpass123"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "AGUARDANDO"})

    def test_login_negado_user(self):
        self.test_client.post(
            "/register",
            json={"email": "denied_lg@test.com", "password": "validpass123", "name": "Denied"},
        )
        self.test_client.patch(
            "/admin/users/denied_lg@test.com/status",
            json={"status": "negado"},
            headers=self.admin_headers,
        )

        response = self.test_client.post(
            "/login", json={"email": "denied_lg@test.com", "password": "validpass123"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "NEGADO"})

    def test_login_wrong_password(self):
        self.test_client.post(
            "/register",
            json={"email": "wrongpw_lg@test.com", "password": "validpass123", "name": "Wrong"},
        )
        response = self.test_client.post(
            "/login", json={"email": "wrongpw_lg@test.com", "password": "wrongpassword"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Credenciais inválidas"})

    def test_login_nonexistent_user(self):
        response = self.test_client.post(
            "/login", json={"email": "ghost_lg@test.com", "password": "validpass123"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Credenciais inválidas"})

    def test_login_invalid_email(self):
        response = self.test_client.post(
            "/login", json={"email": "not-an-email", "password": "validpass123"}
        )
        self.assertEqual(response.status_code, 422)
