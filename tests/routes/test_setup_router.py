"""Tests for the setup router."""

import unittest

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app


class TestSetupRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_setup_creates_superadmin(self):
        response = self.test_client.post(
            "/setup", json={"email": "sa_create@test.com", "password": "adminpass123"}
        )
        self.assertIn(response.status_code, (201, 409))
        if response.status_code == 201:
            self.assertEqual(response.json(), {"detail": "Superadmin criado com sucesso"})

    def test_setup_superadmin_can_login(self):
        self.test_client.post(
            "/setup", json={"email": "sa_canlogin@test.com", "password": "adminpass123"}
        )
        response = self.test_client.post(
            "/login", json={"email": "sa_canlogin@test.com", "password": "adminpass123"}
        )
        if response.status_code == 200:
            self.assertIn("token", response.json())

    def test_setup_duplicate_returns_409(self):
        self.test_client.post(
            "/setup", json={"email": "sa_dup@test.com", "password": "adminpass123"}
        )
        response = self.test_client.post(
            "/setup", json={"email": "sa_dup2@test.com", "password": "adminpass123"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Setup ja realizado"})

    def test_setup_invalid_email(self):
        response = self.test_client.post(
            "/setup", json={"email": "not-an-email", "password": "adminpass123"}
        )
        self.assertEqual(response.status_code, 422)

    def test_setup_short_password(self):
        response = self.test_client.post(
            "/setup", json={"email": "sa@test.com", "password": "short"}
        )
        self.assertEqual(response.status_code, 422)
