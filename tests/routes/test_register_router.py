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

    def test_register_responsavel_success(self):
        response = self.test_client.post(
            "/register/responsavel",
            json={"email": "newuser@test.com", "password": "validpass123", "name": "New User"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"detail": "Cadastro realizado. Aguardando aprovacao."})

    def test_register_responsavel_duplicate_email(self):
        self.test_client.post(
            "/register/responsavel",
            json={"email": "duplicate@test.com", "password": "validpass123", "name": "Dup"},
        )
        response = self.test_client.post(
            "/register/responsavel",
            json={"email": "duplicate@test.com", "password": "validpass123", "name": "Dup"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Email already registered"})

    def test_register_responsavel_invalid_email(self):
        response = self.test_client.post(
            "/register/responsavel",
            json={"email": "not-an-email", "password": "validpass123", "name": "Bad"},
        )
        self.assertEqual(response.status_code, 422)

    def test_register_responsavel_short_password(self):
        response = self.test_client.post(
            "/register/responsavel",
            json={"email": "short@test.com", "password": "short", "name": "Short"},
        )
        self.assertEqual(response.status_code, 422)

    def test_register_aluno_success(self):
        response = self.test_client.post(
            "/register/aluno",
            json={"email": "aluno@test.com", "password": "validpass123", "name": "Aluno"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"detail": "Cadastro realizado."})

    def test_register_aluno_duplicate_email(self):
        self.test_client.post(
            "/register/aluno",
            json={"email": "dup_aluno@test.com", "password": "validpass123", "name": "Dup"},
        )
        response = self.test_client.post(
            "/register/aluno",
            json={"email": "dup_aluno@test.com", "password": "validpass123", "name": "Dup"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Email already registered"})
