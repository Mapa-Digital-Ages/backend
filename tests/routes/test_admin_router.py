"""Tests for the admin router."""

import unittest
import uuid

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from tests.helpers import create_approved_user, get_admin_headers, get_admin_id


class TestAdminRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.test_client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_list_users_as_admin(self):
        response = self.test_client.get("/api/admin/users", headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)
        self.assertTrue(len(response.json()) >= 1)

    def test_list_users_filter_by_status(self):
        self.test_client.post(
            "/api/register/guardian",
            json={
                "email": "adm_filter@test.com",
                "password": "validpass123",
                "first_name": "Filter",
                "last_name": "User",
            },
        )
        response = self.test_client.get(
            "/api/admin/users", params={"user_status": "waiting"}, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 200)
        for user in response.json():
            self.assertEqual(user["status"], "waiting")

    def test_list_users_filter_approved(self):
        response = self.test_client.get(
            "/api/admin/users", params={"user_status": "approved"}, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 200)
        for user in response.json():
            self.assertEqual(user["status"], "approved")

    def test_list_users_invalid_status_filter(self):
        response = self.test_client.get(
            "/api/admin/users", params={"user_status": "invalid"}, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 422)

    def test_list_users_filter_by_role(self):
        self.test_client.post(
            "/api/register/guardian",
            json={
                "email": "adm_role@test.com",
                "password": "validpass123",
                "first_name": "Role",
                "last_name": "User",
            },
        )
        response = self.test_client.get(
            "/api/admin/users", params={"role": "guardian"}, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 200)
        for user in response.json():
            self.assertEqual(user["role"], "guardian")

    def test_list_users_invalid_role_filter(self):
        response = self.test_client.get(
            "/api/admin/users", params={"role": "invalid"}, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 422)

    def test_list_users_without_auth(self):
        response = self.test_client.get("/api/admin/users")
        self.assertEqual(response.status_code, 401)

    def test_list_users_non_admin(self):
        token = create_approved_user(self.test_client, self.admin_headers, "nonadm_list@test.com")
        user_headers = {"Authorization": f"Bearer {token}"}

        response = self.test_client.get("/api/admin/users", headers=user_headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Access restricted to administrators")

    def test_approve_user(self):
        reg = self.test_client.post(
            "/api/register/guardian",
            json={
                "email": "adm_approve@test.com",
                "password": "validpass123",
                "first_name": "Approve",
                "last_name": "User",
            },
        )
        user_id = reg.json()["id"]
        response = self.test_client.patch(
            f"/api/admin/users/{user_id}/status",
            json={"status": "approved"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "approved")

    def test_deny_user(self):
        reg = self.test_client.post(
            "/api/register/guardian",
            json={
                "email": "adm_deny@test.com",
                "password": "validpass123",
                "first_name": "Deny",
                "last_name": "User",
            },
        )
        user_id = reg.json()["id"]
        response = self.test_client.patch(
            f"/api/admin/users/{user_id}/status",
            json={"status": "rejected"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "rejected")

    def test_update_status_user_not_found(self):
        response = self.test_client.patch(
            f"/api/admin/users/{uuid.uuid4()}/status",
            json={"status": "approved"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 404)

    def test_update_status_invalid_status(self):
        response = self.test_client.patch(
            f"/api/admin/users/{uuid.uuid4()}/status",
            json={"status": "invalid"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_update_status_without_auth(self):
        response = self.test_client.patch(
            f"/api/admin/users/{uuid.uuid4()}/status", json={"status": "approved"}
        )
        self.assertEqual(response.status_code, 401)

    def test_update_status_non_admin(self):
        token = create_approved_user(self.test_client, self.admin_headers, "nonadm_upd@test.com")
        user_headers = {"Authorization": f"Bearer {token}"}

        response = self.test_client.patch(
            f"/api/admin/users/{uuid.uuid4()}/status",
            json={"status": "rejected"},
            headers=user_headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_cannot_change_superadmin_status(self):
        admin_id = get_admin_id(self.test_client, self.admin_headers)
        response = self.test_client.patch(
            f"/api/admin/users/{admin_id}/status",
            json={"status": "rejected"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 403)
