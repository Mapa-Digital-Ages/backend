"""Tests for the admin router."""

import unittest

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from tests.helpers import ADMIN_EMAIL, create_approved_user, get_admin_headers


class TestAdminRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.test_client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_list_users_as_admin(self):
        response = self.test_client.get("/admin/users", headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)
        self.assertTrue(len(response.json()) >= 1)

    def test_list_users_filter_by_status(self):
        self.test_client.post(
            "/register",
            json={"email": "adm_filter@test.com", "password": "validpass123", "name": "Filter"},
        )
        response = self.test_client.get(
            "/admin/users", params={"user_status": "aguardando"}, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 200)
        for user in response.json():
            self.assertEqual(user["status"], "aguardando")

    def test_list_users_filter_aprovado(self):
        response = self.test_client.get(
            "/admin/users", params={"user_status": "aprovado"}, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 200)
        for user in response.json():
            self.assertEqual(user["status"], "aprovado")

    def test_list_users_invalid_status_filter(self):
        response = self.test_client.get(
            "/admin/users", params={"user_status": "invalido"}, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 422)

    def test_list_users_filter_by_role(self):
        self.test_client.post(
            "/register",
            json={"email": "adm_role@test.com", "password": "validpass123", "name": "Role"},
        )
        response = self.test_client.get(
            "/admin/users", params={"role": "responsavel"}, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 200)
        for user in response.json():
            self.assertEqual(user["role"], "responsavel")

    def test_list_users_invalid_role_filter(self):
        response = self.test_client.get(
            "/admin/users", params={"role": "invalido"}, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 422)

    def test_list_users_without_auth(self):
        response = self.test_client.get("/admin/users")
        self.assertEqual(response.status_code, 401)

    def test_list_users_non_admin(self):
        token = create_approved_user(self.test_client, self.admin_headers, "nonadm_list@test.com")
        user_headers = {"Authorization": f"Bearer {token}"}

        response = self.test_client.get("/admin/users", headers=user_headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Acesso restrito a administradores")

    def test_approve_user(self):
        self.test_client.post(
            "/register",
            json={"email": "adm_approve@test.com", "password": "validpass123", "name": "Approve"},
        )
        response = self.test_client.patch(
            "/admin/users/adm_approve@test.com/status",
            json={"status": "aprovado"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "aprovado")

    def test_deny_user(self):
        self.test_client.post(
            "/register",
            json={"email": "adm_deny@test.com", "password": "validpass123", "name": "Deny"},
        )
        response = self.test_client.patch(
            "/admin/users/adm_deny@test.com/status",
            json={"status": "negado"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "negado")

    def test_update_status_user_not_found(self):
        response = self.test_client.patch(
            "/admin/users/nonexistent@test.com/status",
            json={"status": "aprovado"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 404)

    def test_update_status_invalid_status(self):
        response = self.test_client.patch(
            "/admin/users/someone@test.com/status",
            json={"status": "invalido"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_update_status_without_auth(self):
        response = self.test_client.patch(
            "/admin/users/someone@test.com/status", json={"status": "aprovado"}
        )
        self.assertEqual(response.status_code, 401)

    def test_update_status_non_admin(self):
        token = create_approved_user(self.test_client, self.admin_headers, "nonadm_upd@test.com")
        user_headers = {"Authorization": f"Bearer {token}"}

        response = self.test_client.patch(
            "/admin/users/nonadm_upd@test.com/status",
            json={"status": "negado"},
            headers=user_headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_cannot_change_superadmin_status(self):
        response = self.test_client.patch(
            f"/admin/users/{ADMIN_EMAIL}/status",
            json={"status": "negado"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 403)
