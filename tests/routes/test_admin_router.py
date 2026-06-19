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
        data={"activity_type": "activity"},
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

    def _create_partnership_fixture(self):
        school_email = f"admin.partner.school.{uuid.uuid4()}@example.com"
        school_password = "securepass123"
        school_response = self.test_client.post(
            "/api/school",
            json={
                "first_name": "Admin",
                "last_name": "Partner School",
                "email": school_email,
                "password": school_password,
                "is_private": False,
            },
            headers=self.admin_headers,
        )
        school_id = school_response.json()["user_id"]
        school_login = self.test_client.post(
            "/api/login", json={"email": school_email, "password": school_password}
        )
        school_headers = {"Authorization": f"Bearer {school_login.json()['token']}"}

        request_response = self.test_client.post(
            f"/api/school/{school_id}/requests",
            json={"title": "Pedido administrativo", "requested_spots": 12},
            headers=school_headers,
        )
        request_id = request_response.json()["id"]

        company_email = f"admin.partner.company.{uuid.uuid4()}@example.com"
        company_password = "securepass123"
        company_response = self.test_client.post(
            "/api/company",
            json={
                "first_name": "Admin",
                "last_name": "Partner Company",
                "email": company_email,
                "password": company_password,
                "spots": 20,
            },
        )
        company_id = company_response.json()["user_id"]
        company_login = self.test_client.post(
            "/api/login", json={"email": company_email, "password": company_password}
        )
        company_headers = {"Authorization": f"Bearer {company_login.json()['token']}"}

        partnership_response = self.test_client.post(
            f"/api/company/{company_id}/partnerships",
            json={"request_id": request_id, "granted_spots": 5},
            headers=company_headers,
        )

        return {
            "company_id": company_id,
            "partnership_id": partnership_response.json()["id"],
            "request_id": request_id,
            "school_id": school_id,
        }

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

    def test_list_users_filter_by_company_role(self):
        self.test_client.post(
            "/api/company",
            json={
                "email": "adm_company_role@test.com",
                "password": "validpass123",
                "first_name": "Company",
                "last_name": "User",
                "spots": 10,
            },
        )
        response = self.test_client.get(
            "/api/admin/users", params={"role": "company"}, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(response.json()) >= 1)
        for user in response.json():
            self.assertEqual(user["role"], "company")

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

    def test_list_partnerships_returns_enriched_items(self):
        fixture = self._create_partnership_fixture()

        response = self.test_client.get("/api/admin/partnerships", headers=self.admin_headers)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        item = next(i for i in body["items"] if i["id"] == fixture["partnership_id"])
        self.assertEqual(item["school_id"], fixture["school_id"])
        self.assertEqual(item["school_name"], "Admin Partner School")
        self.assertEqual(item["company_id"], fixture["company_id"])
        self.assertEqual(item["company_name"], "Admin Partner Company")
        self.assertEqual(item["request_id"], fixture["request_id"])
        self.assertEqual(item["request_title"], "Pedido administrativo")
        self.assertEqual(item["requested_spots"], 12)
        self.assertEqual(item["remaining_spots"], 7)
        self.assertEqual(item["granted_spots"], 5)
        self.assertEqual(item["status"], "pending")

    def test_approve_partnership_status(self):
        fixture = self._create_partnership_fixture()

        response = self.test_client.patch(
            f"/api/admin/partnerships/{fixture['partnership_id']}/status",
            json={"status": "APPROVED"},
            headers=self.admin_headers,
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], fixture["partnership_id"])
        self.assertEqual(body["status"], "approved")
        self.assertEqual(body["school_name"], "Admin Partner School")
        self.assertEqual(body["company_name"], "Admin Partner Company")
        self.assertEqual(body["request_title"], "Pedido administrativo")

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
                "uploads_count",
                "references_count",
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
        subjects_response = self.test_client.get("/api/admin/subjects", headers=self.admin_headers)
        self.assertEqual(subjects_response.status_code, 200)
        subjects = subjects_response.json()
        mathematics = next(subject for subject in subjects if subject["name"] == "Matemática")
        portuguese = next(subject for subject in subjects if subject["name"] == "Português")

        create_response = self.test_client.post(
            "/api/admin/content",
            json={
                "title": "Avaliação bimestral",
                "subject_id": int(mathematics["id"]),
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
                "subject_id": int(portuguese["id"]),
                "description": "Conteúdo de revisão.",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["title"], "Avaliação bimestral revisada")
        self.assertEqual(update_response.json()["subject"]["name"], "Português")

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
            f"/api/admin/uploads/{upload['id']}",
            json={"status": "in_review"},
            headers=self.admin_headers,
        )
        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.json()["status"], "in_review")

        status_response = self.test_client.patch(
            f"/api/admin/uploads/{upload['id']}",
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

    def test_create_resource_with_valid_pdf(self):
        """Test creating a resource with a valid PDF file."""
        # Create a subject and content first
        subject_response = self.test_client.get("/api/admin/subjects", headers=self.admin_headers)
        subjects = subject_response.json()
        subject_id = subjects[0]["id"]

        content_response = self.test_client.post(
            "/api/admin/content",
            json={
                "title": "Resource Test Content",
                "subject_id": int(subject_id),
                "description": "Content for testing resource upload",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(content_response.status_code, 201)
        content_id = content_response.json()["id"]

        # Upload a valid PDF resource
        valid_pdf = b"%PDF-1.4 valid content"
        response = self.test_client.post(
            f"/api/admin/contents/{content_id}/resources",
            data={"title": "Valid PDF", "type": "pdf"},
            files={"file": ("valid.pdf", io.BytesIO(valid_pdf), "application/pdf")},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 201)
        resource = response.json()
        self.assertEqual(resource["title"], "Valid PDF")
        self.assertEqual(resource["type"], "pdf")

    def test_create_resource_with_malicious_file(self):
        """Test that files with adultered extensions are rejected."""
        # Create a subject and content first
        subject_response = self.test_client.get("/api/admin/subjects", headers=self.admin_headers)
        subjects = subject_response.json()
        subject_id = subjects[0]["id"]

        content_response = self.test_client.post(
            "/api/admin/content",
            json={
                "title": "Security Test Content",
                "subject_id": int(subject_id),
                "description": "Content for testing security",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(content_response.status_code, 201)
        content_id = content_response.json()["id"]

        # Upload file with .pdf extension but .exe magic bytes (malicious)
        exe_magic_bytes = b"MZ\x90\x00"  # EXE header
        response = self.test_client.post(
            f"/api/admin/contents/{content_id}/resources",
            data={"title": "Malicious File", "type": "pdf"},
            files={"file": ("malicious.pdf", io.BytesIO(exe_magic_bytes), "application/pdf")},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("magic bytes", response.json()["detail"].lower())

    def test_create_link_resource_without_file(self):
        """Test creating a link resource without file upload."""
        # Create a subject and content first
        subject_response = self.test_client.get("/api/admin/subjects", headers=self.admin_headers)
        subjects = subject_response.json()
        subject_id = subjects[0]["id"]

        content_response = self.test_client.post(
            "/api/admin/content",
            json={
                "title": "Link Test Content",
                "subject_id": int(subject_id),
                "description": "Content for testing link resources",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(content_response.status_code, 201)
        content_id = content_response.json()["id"]

        # Create a link resource (no file upload needed)
        response = self.test_client.post(
            f"/api/admin/contents/{content_id}/resources",
            data={
                "title": "External Resource",
                "type": "link",
                "url_or_contents": "https://example.com/resource",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 201)
        resource = response.json()
        self.assertEqual(resource["title"], "External Resource")
        self.assertEqual(resource["type"], "link")

    def test_create_resource_link_rejects_file(self):
        """Test that link resources reject file uploads."""
        # Create a subject and content first
        subject_response = self.test_client.get("/api/admin/subjects", headers=self.admin_headers)
        subjects = subject_response.json()
        subject_id = subjects[0]["id"]

        content_response = self.test_client.post(
            "/api/admin/content",
            json={
                "title": "Link File Test Content",
                "subject_id": int(subject_id),
                "description": "Content for testing link file rejection",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(content_response.status_code, 201)
        content_id = content_response.json()["id"]

        # Try to upload file with link type (should be rejected)
        response = self.test_client.post(
            f"/api/admin/contents/{content_id}/resources",
            data={
                "title": "Invalid Link",
                "type": "link",
                "url_or_contents": "https://example.com",
            },
            files={"file": ("unwanted.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("file should not be provided", response.json()["detail"].lower())

    def test_create_resource_without_authorization(self):
        """Test that non-admin users cannot create resources."""
        # Create a non-admin user
        token = create_approved_user(
            self.test_client, self.admin_headers, "nonadm_resource@test.com"
        )
        user_headers = {"Authorization": f"Bearer {token}"}

        # Get a subject and content
        subject_response = self.test_client.get("/api/admin/subjects", headers=self.admin_headers)
        subjects = subject_response.json()
        subject_id = subjects[0]["id"]

        content_response = self.test_client.post(
            "/api/admin/content",
            json={
                "title": "Auth Test Content",
                "subject_id": int(subject_id),
                "description": "Content for testing authorization",
            },
            headers=self.admin_headers,
        )
        content_id = content_response.json()["id"]

        # Try to create resource as non-admin (should be rejected)
        response = self.test_client.post(
            f"/api/admin/contents/{content_id}/resources",
            data={"title": "Unauthorized", "type": "pdf"},
            files={"file": ("file.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
            headers=user_headers,
        )
        self.assertEqual(response.status_code, 403)
