"""Tests for authenticated guardian profile routes."""

import unittest

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from tests.helpers import create_approved_user, get_admin_headers


class TestGuardianSelfRoutes(unittest.TestCase):
    """End-to-end tests for /guardian/me routes used by the parent module."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_guardian_can_update_own_profile(self):
        token = create_approved_user(
            self.client,
            self.admin_headers,
            "guardian_self_update@example.com",
            first_name="Old",
            last_name="Name",
        )

        response = self.client.patch(
            "/guardian/me",
            json={
                "email": "guardian_self_updated@example.com",
                "first_name": "New",
                "last_name": "Guardian",
                "phone_number": "+5551999999999",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["email"], "guardian_self_updated@example.com")
        self.assertEqual(body["first_name"], "New")
        self.assertEqual(body["last_name"], "Guardian")
        self.assertEqual(body["phone_number"], "+5551999999999")

    def test_guardian_can_disable_own_profile(self):
        token = create_approved_user(
            self.client,
            self.admin_headers,
            "guardian_self_disable@example.com",
        )

        response = self.client.patch(
            "/guardian/me/disable",
            headers={"Authorization": f"Bearer {token}"},
        )
        me_response = self.client.get(
            "/guardian/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(me_response.status_code, 403)
