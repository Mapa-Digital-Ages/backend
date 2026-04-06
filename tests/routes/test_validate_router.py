"""Tests for the validate router."""

import datetime
import unittest

import jwt
from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from md_backend.utils.security import create_access_token


class TestValidateRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()
        self.valid_token = create_access_token({"sub": "test@test.com", "user_id": 1})
        self.auth_header = {"Authorization": f"Bearer {self.valid_token}"}

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_validate_success_with_token(self):
        text = "text"
        sender = "dummy"
        send_content = {"text": text, "sender": sender}

        response = self.test_client.post("/validate", json=send_content, headers=self.auth_header)

        test_variable = "test"
        check_message = f"{sender} sent the message '{text}' with variable {test_variable}"

        self.assertEqual(response.status_code, 200)
        self.assertEqual(check_message, response.json())

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
        tampered = self.valid_token[:-4] + "XXXX"
        send_content = {"text": "text", "sender": "dummy"}
        headers = {"Authorization": f"Bearer {tampered}"}

        response = self.test_client.post("/validate", json=send_content, headers=headers)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid token")
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_validate_wrong_scheme(self):
        send_content = {"text": "text", "sender": "dummy"}
        headers = {"Authorization": f"Basic {self.valid_token}"}

        response = self.test_client.post("/validate", json=send_content, headers=headers)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
