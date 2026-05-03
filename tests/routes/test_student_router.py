"""Tests for the /student router."""

import asyncio
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

import tests.keys_test  # noqa: F401
from md_backend.main import app
from tests.helpers import create_approved_user, get_admin_headers


def _student_payload(email, *, first_name="John", last_name="Doe"):
    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "password": "securepass123",
        "birth_date": "2010-05-20",
        "student_class": "5th class",
    }


class TestStudentRouterValidation(unittest.TestCase):
    """Validation tests against POST /student (Pydantic 422)."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        self.valid_payload = _student_payload("validation@example.com")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_missing_first_name_returns_422(self):
        payload = {**self.valid_payload}
        del payload["first_name"]
        response = self.client.post("/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_missing_last_name_returns_422(self):
        payload = {**self.valid_payload}
        del payload["last_name"]
        response = self.client.post("/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_invalid_email_returns_422(self):
        payload = {**self.valid_payload, "email": "not-an-email"}
        response = self.client.post("/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_password_too_short_returns_422(self):
        payload = {**self.valid_payload, "password": "123"}
        response = self.client.post("/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_invalid_birth_date_returns_422(self):
        payload = {**self.valid_payload, "birth_date": "not-a-date"}
        response = self.client.post("/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_invalid_student_class_returns_422(self):
        payload = {**self.valid_payload, "student_class": "5A"}
        response = self.client.post("/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_missing_student_class_returns_422(self):
        payload = {**self.valid_payload}
        del payload["student_class"]
        response = self.client.post("/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)


class TestStudentRouterIntegration(unittest.TestCase):
    """End-to-end tests that exercise the full /student CRUD."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    # ------------------------------------------------------------------
    # POST /student
    # ------------------------------------------------------------------

    def test_create_student_success_returns_201(self):
        response = self.client.post(
            "/student",
            json=_student_payload("student_create_ok@example.com"),
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["first_name"], "John")
        self.assertEqual(data["last_name"], "Doe")
        self.assertEqual(data["email"], "student_create_ok@example.com")
        self.assertEqual(data["student_class"], "5th class")
        self.assertNotIn("password", data)
        self.assertIn("id", data)
        self.assertIn("user_id", data)
        uuid.UUID(data["user_id"])

    def test_create_student_with_optional_fields_persists(self):
        from md_backend.models.db_models import StudentProfile, UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        school_resp = self.client.post(
            "/school",
            json={
                "first_name": "School",
                "last_name": "Host",
                "email": "student_create_school@test.com",
                "password": "password1234",
                "is_private": True,
            },
            headers=self.admin_headers,
        )
        school_id = school_resp.json()["user_id"]

        payload = _student_payload("student_create_optional@example.com")
        payload["phone_number"] = "+5511666665555"
        payload["school_id"] = school_id

        response = self.client.post("/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["phone_number"], "+5511666665555")
        self.assertEqual(body["school_id"], school_id)

        async def fetch():
            async with AsyncSessionLocal() as session:
                user_row = await session.execute(
                    select(UserProfile).where(
                        UserProfile.email == "student_create_optional@example.com"
                    )
                )
                user = user_row.scalar_one()
                student_row = await session.execute(
                    select(StudentProfile).where(StudentProfile.user_id == user.id)
                )
                return user, student_row.scalar_one()

        user, student = asyncio.run(fetch())
        self.assertEqual(user.phone_number, "+5511666665555")
        self.assertEqual(student.school_id, uuid.UUID(school_id))

    def test_create_student_without_optional_fields_persists_null(self):
        from md_backend.models.db_models import StudentProfile, UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        response = self.client.post(
            "/student",
            json=_student_payload("student_create_no_optional@example.com"),
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 201)

        async def fetch():
            async with AsyncSessionLocal() as session:
                user_row = await session.execute(
                    select(UserProfile).where(
                        UserProfile.email == "student_create_no_optional@example.com"
                    )
                )
                user = user_row.scalar_one()
                student_row = await session.execute(
                    select(StudentProfile).where(StudentProfile.user_id == user.id)
                )
                return user, student_row.scalar_one()

        user, student = asyncio.run(fetch())
        self.assertIsNone(user.phone_number)
        self.assertIsNone(student.school_id)

    def test_duplicate_email_returns_409(self):
        payload = _student_payload("student_dup@example.com")
        self.client.post("/student", json=payload, headers=self.admin_headers)
        response = self.client.post("/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Email already registered"})

    def test_unauthenticated_returns_401(self):
        response = self.client.post("/student", json=_student_payload("student_unauth@example.com"))
        self.assertEqual(response.status_code, 401)

    def test_non_superadmin_returns_403(self):
        token = create_approved_user(
            self.client, self.admin_headers, "student_nonadmin@example.com"
        )
        response = self.client.post(
            "/student",
            json=_student_payload("student_forbidden@example.com"),
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Access restricted to administrators")

    # ------------------------------------------------------------------
    # GET /student (list)
    # ------------------------------------------------------------------

    def test_list_students_returns_active_students(self):
        self.client.post(
            "/student",
            json=_student_payload("student_list_a@example.com", first_name="Alice"),
            headers=self.admin_headers,
        )
        self.client.post(
            "/student",
            json=_student_payload("student_list_b@example.com", first_name="Bob"),
            headers=self.admin_headers,
        )

        response = self.client.get("/student", headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) >= 2)
        for item in data:
            self.assertNotIn("password", item)
            self.assertTrue(item["is_active"])

    def test_list_students_filter_by_name(self):
        self.client.post(
            "/student",
            json=_student_payload("student_filter_name@example.com", first_name="Zelda"),
            headers=self.admin_headers,
        )

        response = self.client.get("/student", params={"name": "zelda"}, headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertTrue(any(item["first_name"] == "Zelda" for item in items))

    def test_list_students_filter_by_email(self):
        self.client.post(
            "/student",
            json=_student_payload("student_filter_email@example.com"),
            headers=self.admin_headers,
        )

        response = self.client.get(
            "/student",
            params={"email": "student_filter_email"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertTrue(any(item["email"] == "student_filter_email@example.com" for item in items))

    def test_list_students_unauthenticated_returns_401(self):
        response = self.client.get("/student")
        self.assertEqual(response.status_code, 401)

    # ------------------------------------------------------------------
    # GET /student/{id}
    # ------------------------------------------------------------------

    def test_get_student_by_id_returns_200(self):
        create_resp = self.client.post(
            "/student",
            json=_student_payload("student_getbyid@example.com"),
            headers=self.admin_headers,
        )
        student_id = create_resp.json()["user_id"]

        response = self.client.get(f"/student/{student_id}", headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user_id"], student_id)
        self.assertEqual(body["email"], "student_getbyid@example.com")

    def test_get_student_not_found_returns_404(self):
        response = self.client.get(f"/student/{uuid.uuid4()}", headers=self.admin_headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Student not found")

    # ------------------------------------------------------------------
    # PUT /student/{id}
    # ------------------------------------------------------------------

    def test_update_student_changes_fields(self):
        from md_backend.models.api_models import CreateSchoolRequest  # noqa: F401

        school_create = self.client.post(
            "/school",
            json={
                "first_name": "School",
                "last_name": "Host",
                "email": "student_school_host@test.com",
                "password": "password1234",
                "is_private": True,
            },
            headers=self.admin_headers,
        )
        school_id = school_create.json()["user_id"]

        create_resp = self.client.post(
            "/student",
            json=_student_payload("student_update@example.com"),
            headers=self.admin_headers,
        )
        student_id = create_resp.json()["user_id"]

        response = self.client.put(
            f"/student/{student_id}",
            json={
                "first_name": "Updated",
                "last_name": "Name",
                "phone_number": "+5500000000",
                "birth_date": "2011-01-01",
                "student_class": "6th class",
                "school_id": school_id,
            },
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["first_name"], "Updated")
        self.assertEqual(body["last_name"], "Name")
        self.assertEqual(body["phone_number"], "+5500000000")
        self.assertEqual(body["student_class"], "6th class")
        self.assertEqual(body["school_id"], school_id)

    def test_update_student_partial_skips_none_fields(self):
        create_resp = self.client.post(
            "/student",
            json=_student_payload("student_partial@example.com"),
            headers=self.admin_headers,
        )
        student_id = create_resp.json()["user_id"]

        response = self.client.put(
            f"/student/{student_id}",
            json={"first_name": "OnlyFirst"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["first_name"], "OnlyFirst")
        self.assertEqual(body["last_name"], "Doe")
        self.assertEqual(body["student_class"], "5th class")

    def test_update_student_not_found_returns_404(self):
        response = self.client.put(
            f"/student/{uuid.uuid4()}",
            json={"first_name": "Ghost"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Student not found")

    # ------------------------------------------------------------------
    # DELETE /student/{id}
    # ------------------------------------------------------------------

    def test_delete_student_sets_is_active_false(self):
        from md_backend.models.db_models import StudentProfile, UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        create_resp = self.client.post(
            "/student",
            json=_student_payload("student_delete@example.com"),
            headers=self.admin_headers,
        )
        student_id = create_resp.json()["user_id"]

        response = self.client.delete(f"/student/{student_id}", headers=self.admin_headers)
        self.assertEqual(response.status_code, 204)

        async def fetch():
            async with AsyncSessionLocal() as session:
                user_row = await session.execute(
                    select(UserProfile).where(UserProfile.id == uuid.UUID(student_id))
                )
                student_row = await session.execute(
                    select(StudentProfile).where(StudentProfile.user_id == uuid.UUID(student_id))
                )
                return user_row.scalar_one(), student_row.scalar_one()

        user, student = asyncio.run(fetch())
        self.assertFalse(user.is_active)
        self.assertIsNotNone(user.deactivated_at)
        self.assertIsNotNone(student.deactivated_at)

    def test_delete_student_not_found_returns_404(self):
        response = self.client.delete(f"/student/{uuid.uuid4()}", headers=self.admin_headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Student not found")
