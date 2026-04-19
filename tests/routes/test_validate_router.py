"""Tests for the validate router."""

import datetime
import unittest

import jwt
from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from md_backend.utils.security import create_access_token
from tests.helpers import create_approved_user, get_admin_headers


class TestValidateRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.test_client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_validate_success_with_approved_user(self):
        token = create_approved_user(self.test_client, self.admin_headers, "val_ok@test.com")
        headers = {"Authorization": f"Bearer {token}"}
        send_content = {"text": "text", "sender": "dummy"}

        response = self.test_client.post("/validate", json=send_content, headers=headers)

        test_variable = "test"
        check_message = f"dummy sent the message 'text' with variable {test_variable}"

        self.assertEqual(response.status_code, 200)
        self.assertEqual(check_message, response.json())

    def test_validate_aguardando_user_returns_403(self):
        self.test_client.post(
            "/register/responsavel",
            json={"email": "val_wait@test.com", "password": "validpass123", "name": "Wait"},
        )
        self.test_client.patch(
            "/admin/users/val_wait@test.com/status",
            json={"status": "aprovado"},
            headers=self.admin_headers,
        )
        login_resp = self.test_client.post(
            "/login", json={"email": "val_wait@test.com", "password": "validpass123"}
        )
        user_token = login_resp.json()["token"]
        self.test_client.patch(
            "/admin/users/val_wait@test.com/status",
            json={"status": "negado"},
            headers=self.admin_headers,
        )

        headers = {"Authorization": f"Bearer {user_token}"}
        send_content = {"text": "text", "sender": "dummy"}
        response = self.test_client.post("/validate", json=send_content, headers=headers)

        self.assertEqual(response.status_code, 403)

    def test_validate_missing_auth_header(self):
        send_content = {"text": "text", "sender": "dummy"}
        response = self.test_client.post("/validate", json=send_content)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Missing authorization header")
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_validate_invalid_token(self):
        send_content = {"text": "text", "sender": "dummy"}
        headers = {"Authorization": "Bearer garbage-token"}

        response = self.test_client.post("/validate", json=send_content, headers=headers)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid token")
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_validate_expired_token(self):
        expired_token = jwt.encode(
            {
                "sub": "test@test.com",
                "user_id": 1,
                "exp": datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1),
            },
            "test-secret-key",
            algorithm="HS256",
        )
        send_content = {"text": "text", "sender": "dummy"}
        headers = {"Authorization": f"Bearer {expired_token}"}

        response = self.test_client.post("/validate", json=send_content, headers=headers)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Token expired")
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_validate_tampered_token(self):
        token = create_approved_user(self.test_client, self.admin_headers, "val_tamper@test.com")
        tampered = token[:-4] + "XXXX"
        send_content = {"text": "text", "sender": "dummy"}
        headers = {"Authorization": f"Bearer {tampered}"}

        response = self.test_client.post("/validate", json=send_content, headers=headers)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid token")
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_validate_wrong_scheme(self):
        token = create_approved_user(self.test_client, self.admin_headers, "val_scheme@test.com")
        send_content = {"text": "text", "sender": "dummy"}
        headers = {"Authorization": f"Basic {token}"}

        response = self.test_client.post("/validate", json=send_content, headers=headers)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_validate_nonexistent_user_token(self):
        token = create_access_token({"sub": "ghost@test.com", "user_id": 99999})
        headers = {"Authorization": f"Bearer {token}"}
        send_content = {"text": "text", "sender": "dummy"}

        response = self.test_client.post("/validate", json=send_content, headers=headers)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Usuario nao encontrado")
