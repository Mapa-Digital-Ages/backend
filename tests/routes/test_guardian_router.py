"""Tests for authenticated guardian profile routes."""

import unittest
import uuid

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from tests.helpers import create_approved_user, get_admin_headers


def _create_guardian(client, admin_headers, email, password="pass12345"):
    """Create guardian via admin and return (guardian_id, token)."""
    resp = client.post(
        "/api/guardian",
        json={
            "first_name": "Guard",
            "last_name": "Ian",
            "email": email,
            "password": password,
        },
        headers=admin_headers,
    )
    guardian_id = resp.json()["user_id"]
    client.patch(
        f"/api/admin/users/{guardian_id}/status",
        json={"status": "approved"},
        headers=admin_headers,
    )
    token_resp = client.post("/api/login", json={"email": email, "password": password})
    return guardian_id, token_resp.json()["token"]


def _create_student(client, admin_headers, email):
    """Create student via admin and return student_id."""
    resp = client.post(
        "/api/student",
        json={
            "first_name": "Stu",
            "last_name": "Dent",
            "email": email,
            "password": "securepass123",
            "birth_date": "2010-01-01",
            "student_class": "5th class",
        },
        headers=admin_headers,
    )
    return resp.json()["user_id"]


class TestGuardianSelfRoutes(unittest.TestCase):
    """End-to-end tests for /guardian/me routes used by the parent module."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_guardian_can_get_own_profile(self):
        """Authenticated guardian reads their own /me profile."""
        token = create_approved_user(
            self.client,
            self.admin_headers,
            f"guardian_self_get_{uuid.uuid4().hex[:6]}@example.com",
            first_name="Self",
            last_name="Reader",
        )

        response = self.client.get(
            "/api/guardian/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["first_name"], "Self")
        self.assertEqual(body["last_name"], "Reader")
        self.assertIn("students", body)

    def test_guardian_can_update_own_profile(self):
        token = create_approved_user(
            self.client,
            self.admin_headers,
            "guardian_self_update@example.com",
            first_name="Old",
            last_name="Name",
        )

        response = self.client.patch(
            "/api/guardian/me",
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

    def test_guardian_can_delete_own_profile(self):
        token = create_approved_user(
            self.client,
            self.admin_headers,
            "guardian_self_delete@example.com",
        )

        response = self.client.delete(
            "/api/guardian/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        me_response = self.client.get(
            "/api/guardian/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(me_response.status_code, 403)

    def test_get_me_returns_404_for_non_guardian(self):
        """Admin (no guardian profile) accessing /guardian/me gets 404."""
        response = self.client.get("/api/guardian/me", headers=self.admin_headers)
        self.assertEqual(response.status_code, 404)

    def test_update_me_returns_404_for_non_guardian(self):
        """Admin (no guardian profile) PATCH /guardian/me gets 404."""
        response = self.client.patch(
            "/api/guardian/me",
            json={"first_name": "X"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 404)

    def test_update_me_email_conflict_returns_409(self):
        """Updating to an already-used email returns 409."""
        _, token1 = _create_guardian(
            self.client,
            self.admin_headers,
            f"guardian_me_conflict_a_{uuid.uuid4().hex[:6]}@example.com",
        )
        existing_email = f"guardian_me_conflict_b_{uuid.uuid4().hex[:6]}@example.com"
        _create_guardian(self.client, self.admin_headers, existing_email)

        response = self.client.patch(
            "/api/guardian/me",
            json={"email": existing_email},
            headers={"Authorization": f"Bearer {token1}"},
        )
        self.assertEqual(response.status_code, 409)

    def test_delete_me_returns_404_for_non_guardian(self):
        """Admin (no guardian profile) DELETE /guardian/me gets 404."""
        response = self.client.delete("/api/guardian/me", headers=self.admin_headers)
        self.assertEqual(response.status_code, 404)


class TestGuardianAdminRoutes(unittest.TestCase):
    """Admin-only CRUD tests for /guardian."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_create_guardian_duplicate_email_returns_409(self):
        email = f"guardian_dup_{uuid.uuid4().hex[:6]}@example.com"
        payload = {
            "first_name": "G",
            "last_name": "Dup",
            "email": email,
            "password": "pass12345",
        }
        self.client.post("/api/guardian", json=payload, headers=self.admin_headers)
        resp = self.client.post("/api/guardian", json=payload, headers=self.admin_headers)
        self.assertEqual(resp.status_code, 409)

    def test_list_guardians_with_name_filter(self):
        email = f"guardian_listname_{uuid.uuid4().hex[:6]}@example.com"
        _create_guardian(self.client, self.admin_headers, email)
        resp = self.client.get(
            "/api/guardian", params={"name": "Guard"}, headers=self.admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("items", resp.json())

    def test_list_guardians_with_email_filter(self):
        email = f"guardian_listemail_{uuid.uuid4().hex[:6]}@example.com"
        _create_guardian(self.client, self.admin_headers, email)
        resp = self.client.get(
            "/api/guardian", params={"email": "guardian_listemail"}, headers=self.admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("items", resp.json())

    def test_list_guardians_with_status_filter(self):
        resp = self.client.get(
            "/api/guardian", params={"guardian_status": "waiting"}, headers=self.admin_headers
        )
        self.assertEqual(resp.status_code, 200)

    def test_get_guardian_by_id_returns_200(self):
        email = f"guardian_getbyid_{uuid.uuid4().hex[:6]}@example.com"
        guardian_id, _ = _create_guardian(self.client, self.admin_headers, email)
        resp = self.client.get(f"/api/guardian/{guardian_id}", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user_id"], guardian_id)

    def test_get_guardian_by_id_not_found_returns_404(self):
        resp = self.client.get(f"/api/guardian/{uuid.uuid4()}", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 404)

    def test_update_guardian_by_id_returns_200(self):
        email = f"guardian_update_{uuid.uuid4().hex[:6]}@example.com"
        guardian_id, _ = _create_guardian(self.client, self.admin_headers, email)
        resp = self.client.patch(
            f"/api/guardian/{guardian_id}",
            json={"first_name": "Updated"},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["first_name"], "Updated")

    def test_update_guardian_by_id_not_found_returns_404(self):
        resp = self.client.patch(
            f"/api/guardian/{uuid.uuid4()}",
            json={"first_name": "Ghost"},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_update_guardian_by_id_email_conflict_returns_409(self):
        email_a = f"guardian_upd_a_{uuid.uuid4().hex[:6]}@example.com"
        email_b = f"guardian_upd_b_{uuid.uuid4().hex[:6]}@example.com"
        guardian_id_a, _ = _create_guardian(self.client, self.admin_headers, email_a)
        _create_guardian(self.client, self.admin_headers, email_b)
        resp = self.client.patch(
            f"/api/guardian/{guardian_id_a}",
            json={"email": email_b},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 409)

    def test_delete_guardian_by_id_returns_204(self):
        email = f"guardian_del_{uuid.uuid4().hex[:6]}@example.com"
        guardian_id, _ = _create_guardian(self.client, self.admin_headers, email)
        resp = self.client.delete(f"/api/guardian/{guardian_id}", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 204)

    def test_delete_guardian_by_id_not_found_returns_404(self):
        resp = self.client.delete(f"/api/guardian/{uuid.uuid4()}", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 404)

    def test_link_student_not_found_returns_404(self):
        email = f"guardian_link_{uuid.uuid4().hex[:6]}@example.com"
        guardian_id, _ = _create_guardian(self.client, self.admin_headers, email)
        resp = self.client.post(
            f"/api/guardian/{guardian_id}/students/{uuid.uuid4()}",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_link_guardian_not_found_returns_404(self):
        student_email = f"link_student_{uuid.uuid4().hex[:6]}@example.com"
        student_id = _create_student(self.client, self.admin_headers, student_email)
        resp = self.client.post(
            f"/api/guardian/{uuid.uuid4()}/students/{student_id}",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_link_already_linked_returns_404(self):
        guardian_email = f"guardian_dup_link_{uuid.uuid4().hex[:6]}@example.com"
        student_email = f"student_dup_link_{uuid.uuid4().hex[:6]}@example.com"
        guardian_id, _ = _create_guardian(self.client, self.admin_headers, guardian_email)
        student_id = _create_student(self.client, self.admin_headers, student_email)
        self.client.post(
            f"/api/guardian/{guardian_id}/students/{student_id}",
            headers=self.admin_headers,
        )
        resp = self.client.post(
            f"/api/guardian/{guardian_id}/students/{student_id}",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_unlink_student_returns_204(self):
        guardian_email = f"guardian_unlink_{uuid.uuid4().hex[:6]}@example.com"
        student_email = f"student_unlink_{uuid.uuid4().hex[:6]}@example.com"
        guardian_id, _ = _create_guardian(self.client, self.admin_headers, guardian_email)
        student_id = _create_student(self.client, self.admin_headers, student_email)
        self.client.post(
            f"/api/guardian/{guardian_id}/students/{student_id}",
            headers=self.admin_headers,
        )
        resp = self.client.delete(
            f"/api/guardian/{guardian_id}/students/{student_id}",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 204)

    def test_unlink_not_linked_returns_404(self):
        guardian_email = f"guardian_unlink_miss_{uuid.uuid4().hex[:6]}@example.com"
        student_email = f"student_unlink_miss_{uuid.uuid4().hex[:6]}@example.com"
        guardian_id, _ = _create_guardian(self.client, self.admin_headers, guardian_email)
        student_id = _create_student(self.client, self.admin_headers, student_email)
        resp = self.client.delete(
            f"/api/guardian/{guardian_id}/students/{student_id}",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_get_guardian_includes_linked_students(self):
        """get_guardian_by_id path with active students."""
        guardian_email = f"guardian_with_student_{uuid.uuid4().hex[:6]}@example.com"
        student_email = f"student_of_guardian_{uuid.uuid4().hex[:6]}@example.com"
        guardian_id, _ = _create_guardian(self.client, self.admin_headers, guardian_email)
        student_id = _create_student(self.client, self.admin_headers, student_email)
        self.client.post(
            f"/api/guardian/{guardian_id}/students/{student_id}",
            headers=self.admin_headers,
        )
        resp = self.client.get(f"/api/guardian/{guardian_id}", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        students = resp.json().get("students", [])
        self.assertTrue(any(s["user_id"] == student_id for s in students))
