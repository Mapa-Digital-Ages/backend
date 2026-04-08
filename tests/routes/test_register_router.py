"""Tests for the register router."""

import unittest

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app


class TestRegisterRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_register_success(self):
        response = self.test_client.post(
            "/register", json={"email": "newuser@test.com", "password": "validpass123"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"detail": "Cadastro realizado. Aguardando aprovacao."})

    def test_register_duplicate_email(self):
        self.test_client.post(
            "/register", json={"email": "duplicate@test.com", "password": "validpass123"}
        )
        response = self.test_client.post(
            "/register", json={"email": "duplicate@test.com", "password": "validpass123"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Email already registered"})

    def test_register_invalid_email(self):
        response = self.test_client.post(
            "/register", json={"email": "not-an-email", "password": "validpass123"}
        )
        self.assertEqual(response.status_code, 422)

    def test_register_short_password(self):
        response = self.test_client.post(
            "/register", json={"email": "short@test.com", "password": "short"}
        )
        self.assertEqual(response.status_code, 422)
