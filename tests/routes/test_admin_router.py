"""Tests for the admin router."""

import io
import unittest
import uuid

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from tests.helpers import create_approved_user, get_admin_headers, get_admin_id


def _make_student(test_client, admin_headers):
    """Create a student and return the user id."""
    payload = {
        "first_name": "Admin",
        "last_name": "Content Student",
        "email": f"admin.content.student.{uuid.uuid4()}@example.com",
        "password": "securepass123",
        "birth_date": "2010-05-20",
        "student_class": "5th class",
    }
    response = test_client.post("/api/student", json=payload, headers=admin_headers)
    return response.json()["user_id"]


def _make_upload(test_client, admin_headers, student_id):
    """Upload a small PDF and return its metadata."""
    response = test_client.post(
        f"/api/student/{student_id}/uploads",
        files={"file": ("atividade.pdf", io.BytesIO(b"%PDF-1.4 content"), "application/pdf")},
        headers=admin_headers,
    )
    return response.json()


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

    def test_subject_catalog_uses_backend_counts_contract(self):
        list_response = self.test_client.get("/api/admin/subjects", headers=self.admin_headers)
        self.assertEqual(list_response.status_code, 200)
        subjects = list_response.json()
        self.assertTrue(any(subject["name"] == "Matemática" for subject in subjects))
        self.assertTrue(
            {
                "id",
                "slug",
                "name",
                "color",
                "content_count",
                "tasks_count",
                "trails_count",
                "questionnaire_count",
            }
            <= set(subjects[0])
        )
        mathematics = next(subject for subject in subjects if subject["name"] == "Matemática")
        self.assertEqual(mathematics["slug"], "mathematics")
        self.assertEqual(mathematics["color"], "rgba(173, 68, 248, 1)")

        subject_name = f"Disciplina {uuid.uuid4()}"
        create_response = self.test_client.post(
            "/api/admin/subjects",
            json={"name": subject_name, "color": "rgba(1, 2, 3, 1)"},
            headers=self.admin_headers,
        )
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()
        self.assertEqual(created["name"], subject_name)
        self.assertEqual(created["color"], "rgba(1, 2, 3, 1)")

        delete_response = self.test_client.delete(
            f"/api/admin/subjects/{created['id']}",
            headers=self.admin_headers,
        )
        self.assertEqual(delete_response.status_code, 204)

    def test_content_crud_and_correction_session(self):
        create_response = self.test_client.post(
            "/api/admin/content",
            json={
                "title": "Avaliação bimestral",
                "subject_label": "Matemática",
                "description": "Conteúdo inicial.",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()

        list_response = self.test_client.get(
            "/api/admin/content",
            params={"query": "bimestral", "status": "sent"},
            headers=self.admin_headers,
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertGreaterEqual(list_response.json()["total_items"], 1)

        update_response = self.test_client.patch(
            f"/api/admin/content/{created['id']}",
            json={
                "title": "Avaliação bimestral revisada",
                "subject_label": "Português",
                "description": "Conteúdo de revisão.",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["title"], "Avaliação bimestral revisada")
        self.assertEqual(update_response.json()["stage_label"], "Português")

        session_response = self.test_client.patch(
            f"/api/admin/content/{created['id']}/correction/status",
            json={"status": "correction_in_progress"},
            headers=self.admin_headers,
        )
        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.json()["status"], "inProgress")

        message_response = self.test_client.post(
            f"/api/admin/content/{created['id']}/correction/messages",
            json={"body": "Revise a questão 2."},
            headers=self.admin_headers,
        )
        self.assertEqual(message_response.status_code, 201)
        self.assertEqual(message_response.json()["messages"][-1]["body"], "Revise a questão 2.")

        delete_response = self.test_client.delete(
            f"/api/admin/content/{created['id']}",
            headers=self.admin_headers,
        )
        self.assertEqual(delete_response.status_code, 204)

    def test_upload_queue_delete_and_correction_session(self):
        student_id = _make_student(self.test_client, self.admin_headers)
        upload = _make_upload(self.test_client, self.admin_headers, student_id)

        list_response = self.test_client.get(
            "/api/admin/uploads",
            params={"query": "atividade", "status": "pending"},
            headers=self.admin_headers,
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertGreaterEqual(list_response.json()["total_items"], 1)
        self.assertEqual(list_response.json()["items"][0]["activity_type"], "activity")
        self.assertEqual(list_response.json()["items"][0]["status"], "pending")

        activity_response = self.test_client.patch(
            f"/api/admin/uploads/{upload['id']}",
            json={"activity_type": "essay"},
            headers=self.admin_headers,
        )
        self.assertEqual(activity_response.status_code, 200)
        self.assertEqual(activity_response.json()["activity_type"], "essay")

        activity_filter_response = self.test_client.get(
            "/api/admin/uploads",
            params={"activity_type": "essay"},
            headers=self.admin_headers,
        )
        self.assertEqual(activity_filter_response.status_code, 200)
        self.assertGreaterEqual(activity_filter_response.json()["total_items"], 1)

        session_response = self.test_client.patch(
            f"/api/admin/uploads/{upload['id']}/correction/status",
            json={"status": "correction_in_progress"},
            headers=self.admin_headers,
        )
        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.json()["status"], "inProgress")

        status_response = self.test_client.patch(
            f"/api/admin/uploads/{upload['id']}/status",
            json={"status": "corrected"},
            headers=self.admin_headers,
        )
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["status"], "corrected")

        delete_response = self.test_client.delete(
            f"/api/admin/uploads/{upload['id']}",
            headers=self.admin_headers,
        )
        self.assertEqual(delete_response.status_code, 204)
