"""Tests for the main app entry point."""

import json
import unittest

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401 - must be imported before md_backend to set env vars
from md_backend.main import app


class TestValidateRouter(unittest.TestCase):
    def setUp(self):
        self.test_client = TestClient(app, raise_server_exceptions=False)

    def test_validate_router(self):
        text = "text"
        sender = "dummy"

        send_content = {"text": text, "sender": sender}

        response = self.test_client.post("/validate", json=send_content)

        test_variable = "test"
        check_message = f"{sender} sent the message '{text}' with variable {test_variable}"

        self.assertEqual(response.status_code, 200)
        self.assertEqual(check_message, response.json())
