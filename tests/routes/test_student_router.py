"""Tests for the /api/student router."""

import asyncio
import datetime
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


def _login_token(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/login", json={"email": email, "password": password})
    return response.json()["token"]


def _create_student_with_token(
    client: TestClient,
    admin_headers: dict[str, str],
    email: str | None = None,
    password: str = "securepass123",
) -> tuple[str, str, str]:
    student_email = email or f"student_{uuid.uuid4().hex[:8]}@example.com"
    payload = {**_student_payload(student_email), "password": password}
    response = client.post("/api/student", json=payload, headers=admin_headers)
    student_id = response.json()["user_id"]
    return student_id, student_email, _login_token(client, student_email, password)


def _create_guardian_with_token(
    client: TestClient,
    admin_headers: dict[str, str],
    email: str | None = None,
    password: str = "guardianpass123",
) -> tuple[str, str]:
    guardian_email = email or f"guardian_{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/guardian",
        json={
            "first_name": "Guardian",
            "last_name": "Owner",
            "email": guardian_email,
            "password": password,
        },
        headers=admin_headers,
    )
    guardian_id = response.json()["user_id"]
    client.patch(
        f"/api/admin/users/{guardian_id}/status",
        json={"status": "approved"},
        headers=admin_headers,
    )
    return guardian_id, _login_token(client, guardian_email, password)


def _link_guardian_to_student(
    client: TestClient,
    admin_headers: dict[str, str],
    guardian_id: str,
    student_id: str,
) -> None:
    response = client.post(
        f"/api/guardian/{guardian_id}/students/{student_id}",
        headers=admin_headers,
    )
    assert response.status_code == 201


class TestStudentRouterValidation(unittest.TestCase):
    """Validation tests against POST /api/student (Pydantic 422)."""

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
        response = self.client.post("/api/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_missing_last_name_returns_422(self):
        payload = {**self.valid_payload}
        del payload["last_name"]
        response = self.client.post("/api/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_invalid_email_returns_422(self):
        payload = {**self.valid_payload, "email": "not-an-email"}
        response = self.client.post("/api/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_password_too_short_returns_422(self):
        payload = {**self.valid_payload, "password": "123"}
        response = self.client.post("/api/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_invalid_birth_date_returns_422(self):
        payload = {**self.valid_payload, "birth_date": "not-a-date"}
        response = self.client.post("/api/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_invalid_student_class_returns_422(self):
        payload = {**self.valid_payload, "student_class": "5A"}
        response = self.client.post("/api/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)

    def test_missing_student_class_returns_422(self):
        payload = {**self.valid_payload}
        del payload["student_class"]
        response = self.client.post("/api/student", json=payload, headers=self.admin_headers)
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
            "/api/student",
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
            "/api/school",
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

        response = self.client.post("/api/student", json=payload, headers=self.admin_headers)
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
            "/api/student",
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
        self.client.post("/api/student", json=payload, headers=self.admin_headers)
        response = self.client.post("/api/student", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Email already registered"})

    def test_unauthenticated_returns_401(self):
        response = self.client.post(
            "/api/student", json=_student_payload("student_unauth@example.com")
        )
        self.assertEqual(response.status_code, 401)

    def test_guardian_can_create_student_and_is_auto_linked(self):
        from md_backend.models.db_models import StudentGuardian, UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        token = create_approved_user(
            self.client, self.admin_headers, "guardian_creator@example.com"
        )
        response = self.client.post(
            "/api/student",
            json=_student_payload("guardian_owned_student@example.com"),
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 201)
        student_user_id = response.json()["user_id"]

        async def fetch_link_and_guardian():
            async with AsyncSessionLocal() as session:
                guardian_user = (
                    await session.execute(
                        select(UserProfile).where(
                            UserProfile.email == "guardian_creator@example.com"
                        )
                    )
                ).scalar_one()
                link_row = (
                    await session.execute(
                        select(StudentGuardian).where(
                            StudentGuardian.guardian_id == guardian_user.id,
                            StudentGuardian.student_id == uuid.UUID(student_user_id),
                            StudentGuardian.deactivated_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                return link_row

        link = asyncio.run(fetch_link_and_guardian())
        self.assertIsNotNone(link, "guardian-student link was not created")

        login_response = self.client.post(
            "/api/login",
            json={
                "email": "guardian_owned_student@example.com",
                "password": "securepass123",
            },
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(login_response.json()["role"], "student")

    # ------------------------------------------------------------------
    # GET /student (list)
    # ------------------------------------------------------------------

    def test_list_students_returns_active_students(self):
        self.client.post(
            "/api/student",
            json=_student_payload("student_list_a@example.com", first_name="Alice"),
            headers=self.admin_headers,
        )
        self.client.post(
            "/api/student",
            json=_student_payload("student_list_b@example.com", first_name="Bob"),
            headers=self.admin_headers,
        )

        response = self.client.get("/api/student", headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 2)
        for item in data:
            self.assertNotIn("password", item)
            self.assertTrue(item["is_active"])

    def test_list_students_filter_by_name(self):
        self.client.post(
            "/api/student",
            json=_student_payload("student_filter_name@example.com", first_name="Zelda"),
            headers=self.admin_headers,
        )

        response = self.client.get(
            "/api/student", params={"name": "zelda"}, headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertTrue(any(item["first_name"] == "Zelda" for item in items))

    def test_list_students_filter_by_email(self):
        self.client.post(
            "/api/student",
            json=_student_payload("student_filter_email@example.com"),
            headers=self.admin_headers,
        )

        response = self.client.get(
            "/api/student",
            params={"email": "student_filter_email"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertTrue(any(item["email"] == "student_filter_email@example.com" for item in items))

    def test_list_students_unauthenticated_returns_401(self):
        response = self.client.get("/api/student")
        self.assertEqual(response.status_code, 401)

    # ------------------------------------------------------------------
    # GET /student/{id}
    # ------------------------------------------------------------------

    def test_get_student_by_id_returns_200(self):
        create_resp = self.client.post(
            "/api/student",
            json=_student_payload("student_getbyid@example.com"),
            headers=self.admin_headers,
        )
        student_id = create_resp.json()["user_id"]

        response = self.client.get(f"/api/student/{student_id}", headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user_id"], student_id)
        self.assertEqual(body["email"], "student_getbyid@example.com")

    def test_get_student_not_found_returns_404(self):
        response = self.client.get(f"/api/student/{uuid.uuid4()}", headers=self.admin_headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Student not found")

    def test_get_deleted_student_returns_404(self):
        create_resp = self.client.post(
            "/api/student",
            json=_student_payload("student_get_deleted@example.com"),
            headers=self.admin_headers,
        )
        student_id = create_resp.json()["user_id"]

        self.client.delete(f"/api/student/{student_id}", headers=self.admin_headers)

        response = self.client.get(f"/api/student/{student_id}", headers=self.admin_headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Student not found")

    # ------------------------------------------------------------------
    # PUT /api/student/{id}
    # ------------------------------------------------------------------

    def test_update_student_changes_fields(self):
        from md_backend.models.api_models import CreateSchoolRequest  # noqa: F401

        school_create = self.client.post(
            "/api/school",
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
            "/api/student",
            json=_student_payload("student_update@example.com"),
            headers=self.admin_headers,
        )
        student_id = create_resp.json()["user_id"]

        response = self.client.put(
            f"/api/student/{student_id}",
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
            "/api/student",
            json=_student_payload("student_partial@example.com"),
            headers=self.admin_headers,
        )
        student_id = create_resp.json()["user_id"]

        response = self.client.put(
            f"/api/student/{student_id}",
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
            f"/api/student/{uuid.uuid4()}",
            json={"first_name": "Ghost"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Student not found")

    # ------------------------------------------------------------------
    # DELETE /api/student/{id}
    # ------------------------------------------------------------------

    def test_delete_student_sets_is_active_false(self):
        from md_backend.models.db_models import StudentProfile, UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        create_resp = self.client.post(
            "/api/student",
            json=_student_payload("student_delete@example.com"),
            headers=self.admin_headers,
        )
        student_id = create_resp.json()["user_id"]

        response = self.client.delete(f"/api/student/{student_id}", headers=self.admin_headers)
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
        response = self.client.delete(f"/api/student/{uuid.uuid4()}", headers=self.admin_headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Student not found")

    # ------------------------------------------------------------------
    # POST /student — non-admin non-guardian → 403
    # ------------------------------------------------------------------

    def test_student_cannot_create_student_returns_403(self):
        student_id, _, token = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_create_denied_{uuid.uuid4().hex[:6]}@example.com",
        )
        response = self.client.post(
            "/api/student",
            json=_student_payload(f"denied_target_{uuid.uuid4().hex[:6]}@example.com"),
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # GET /student/{id} — access denied (non-linked user)
    # ------------------------------------------------------------------

    def test_unrelated_student_cannot_read_other_student(self):
        target_id, _, _ = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_target_{uuid.uuid4().hex[:6]}@example.com",
        )
        _, _, requester_token = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_requester_{uuid.uuid4().hex[:6]}@example.com",
        )
        response = self.client.get(
            f"/api/student/{target_id}",
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # GET /student/{id}/summary, /disciplines, /tasks
    # ------------------------------------------------------------------

    def test_get_student_summary_returns_200(self):
        student_id, _, _ = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_summary_{uuid.uuid4().hex[:6]}@example.com",
        )
        response = self.client.get(
            f"/api/student/{student_id}/summary",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_get_student_disciplines_returns_200(self):
        student_id, _, _ = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_disc_{uuid.uuid4().hex[:6]}@example.com",
        )
        response = self.client.get(
            f"/api/student/{student_id}/disciplines",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_get_student_tasks_returns_200(self):
        student_id, _, _ = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_tasks_{uuid.uuid4().hex[:6]}@example.com",
        )
        response = self.client.get(
            f"/api/student/{student_id}/tasks",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_summary_access_denied_for_unrelated_user(self):
        target_id, _, _ = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_sum_target_{uuid.uuid4().hex[:6]}@example.com",
        )
        _, _, requester_token = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_sum_req_{uuid.uuid4().hex[:6]}@example.com",
        )
        response = self.client.get(
            f"/api/student/{target_id}/summary",
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_disciplines_access_denied_for_unrelated_user(self):
        target_id, _, _ = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_disc_target_{uuid.uuid4().hex[:6]}@example.com",
        )
        _, _, requester_token = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_disc_req_{uuid.uuid4().hex[:6]}@example.com",
        )
        response = self.client.get(
            f"/api/student/{target_id}/disciplines",
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_tasks_access_denied_for_unrelated_user(self):
        target_id, _, _ = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_task_target_{uuid.uuid4().hex[:6]}@example.com",
        )
        _, _, requester_token = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_task_req_{uuid.uuid4().hex[:6]}@example.com",
        )
        response = self.client.get(
            f"/api/student/{target_id}/tasks",
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_student_can_access_own_summary(self):
        student_id, _, token = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_self_{uuid.uuid4().hex[:6]}@example.com",
        )
        response = self.client.get(
            f"/api/student/{student_id}/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 200)

    def test_delete_access_denied_for_non_admin(self):
        target_id, _, _ = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_del_target_{uuid.uuid4().hex[:6]}@example.com",
        )
        _, _, requester_token = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"student_del_req_{uuid.uuid4().hex[:6]}@example.com",
        )
        response = self.client.delete(
            f"/api/student/{target_id}",
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        self.assertEqual(response.status_code, 403)


class TestStudentAdminRouteDeniedBranches(unittest.TestCase):
    """Force the dead `_ensure_can_access_student` branches in PUT/DELETE.

    Real traffic can't reach those branches because both routes require
    `get_current_superadmin` (which 403s before the body runs). We override
    that dependency so a non-admin caller reaches the body with
    ``is_superadmin=False`` and is rejected by the inner access check.
    """

    def setUp(self):
        from md_backend.utils.security import get_current_superadmin

        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        self.target_id, _, _ = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"target_dead_branch_{uuid.uuid4().hex[:6]}@example.com",
        )
        _, _, self.requester_token = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"req_dead_branch_{uuid.uuid4().hex[:6]}@example.com",
        )
        app.dependency_overrides[get_current_superadmin] = lambda: {
            "user_id": "00000000-0000-0000-0000-000000000000",
            "is_superadmin": False,
        }
        self._dep = get_current_superadmin

    def tearDown(self):
        app.dependency_overrides.pop(self._dep, None)
        self.ctx.__exit__(None, None, None)

    def test_put_inner_access_check_returns_403(self):
        response = self.client.put(
            f"/api/student/{self.target_id}",
            json={"first_name": "X"},
            headers={"Authorization": f"Bearer {self.requester_token}"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Access denied")

    def test_delete_inner_access_check_returns_403(self):
        response = self.client.delete(
            f"/api/student/{self.target_id}",
            headers={"Authorization": f"Bearer {self.requester_token}"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Access denied")


class TestWellBeingHistoryExtra(unittest.TestCase):
    """Extra cases for well-being history endpoint."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        self.student_id, _, _ = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"wb_hist_extra_{uuid.uuid4().hex[:8]}@example.com",
        )

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_from_after_to_returns_422(self):
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        response = self.client.get(
            f"/api/student/{self.student_id}/well-being/history",
            params={"from": today.isoformat(), "to": yesterday.isoformat()},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_superadmin_can_read_history(self):
        today = datetime.date.today()
        response = self.client.get(
            f"/api/student/{self.student_id}/well-being/history",
            params={"from": today.isoformat(), "to": today.isoformat()},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)

    def test_superadmin_can_read_daily_well_being(self):
        today = datetime.date.today()
        response = self.client.get(
            f"/api/student/{self.student_id}/well-being",
            params={"date": today.isoformat()},
            headers=self.admin_headers,
        )
        self.assertIn(response.status_code, (200, 404))


class TestWellBeingGetValidation(unittest.TestCase):
    """Validation tests for GET /student/{id}/well-being."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

        unique_email = f"wb_get_val_{uuid.uuid4().hex[:8]}@example.com"
        resp = self.client.post(
            "/api/student",
            json=_student_payload(unique_email),
            headers=self.admin_headers,
        )
        self.student_id = resp.json()["user_id"]

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_invalid_student_uuid_returns_422(self):
        response = self.client.get(
            "/api/student/not-a-uuid/well-being",
            params={"date": "2024-01-01"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_missing_date_param_returns_422(self):
        response = self.client.get(
            f"/api/student/{self.student_id}/well-being",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_invalid_date_format_returns_422(self):
        response = self.client.get(
            f"/api/student/{self.student_id}/well-being",
            params={"date": "01-01-2024"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 422)


class TestWellBeingGetIntegration(unittest.TestCase):
    """Integration tests for GET /student/{id}/well-being."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

        unique_email = f"wb_get_int_{uuid.uuid4().hex[:8]}@example.com"
        resp = self.client.post(
            "/api/student",
            json=_student_payload(unique_email),
            headers=self.admin_headers,
        )
        self.student_id = resp.json()["user_id"]
        self.student_token = _login_token(self.client, unique_email, "securepass123")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_get_well_being_returns_404_when_no_record(self):
        """A date with no record must return 404 (expected empty state)."""
        response = self.client.get(
            f"/api/student/{self.student_id}/well-being",
            params={"date": "2000-01-01"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.json())

    def test_get_well_being_returns_200_with_correct_values(self):
        """After a PUT, the GET for the same date must return the stored values."""
        import datetime

        today = datetime.date.today().isoformat()

        self.client.put(
            f"/api/student/{self.student_id}/well-being",
            json={"humor": "good", "online_activity_minutes": 45, "sleep_hours": 7.5},
            headers={"Authorization": f"Bearer {self.student_token}"},
        )

        response = self.client.get(
            f"/api/student/{self.student_id}/well-being",
            params={"date": today},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["humor"], "good")
        self.assertEqual(body["online_activity_minutes"], 45)
        self.assertAlmostEqual(body["sleep_hours"], 7.5, places=1)
        self.assertEqual(body["student_id"], self.student_id)
        self.assertEqual(body["date"], today)

    def test_get_well_being_unknown_student_returns_404(self):
        """A valid UUID that belongs to no student must return 404."""
        response = self.client.get(
            f"/api/student/{uuid.uuid4()}/well-being",
            params={"date": "2024-01-01"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 404)


class TestWellBeingPutValidation(unittest.TestCase):
    """Unit-level validation tests for PUT /student/{id}/well-being."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

        unique_email = f"wb_put_val_{uuid.uuid4().hex[:8]}@example.com"
        resp = self.client.post(
            "/api/student",
            json=_student_payload(unique_email),
            headers=self.admin_headers,
        )
        self.student_id = resp.json()["user_id"]
        self.student_token = _login_token(self.client, unique_email, "securepass123")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_invalid_humor_enum_returns_400(self):
        """An unrecognised humor string must be rejected with 400."""
        response = self.client.put(
            f"/api/student/{self.student_id}/well-being",
            json={"humor": "ecstatic"},
            headers={"Authorization": f"Bearer {self.student_token}"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("humor", response.json()["detail"])

    def test_negative_online_activity_minutes_returns_422(self):
        """Negative integers for online_activity_minutes must be rejected with 422."""
        response = self.client.put(
            f"/api/student/{self.student_id}/well-being",
            json={"online_activity_minutes": -10},
            headers={"Authorization": f"Bearer {self.student_token}"},
        )
        self.assertEqual(response.status_code, 422)

    def test_sleep_hours_above_24_returns_422(self):
        """sleep_hours above 24 must be rejected with 422."""
        response = self.client.put(
            f"/api/student/{self.student_id}/well-being",
            json={"sleep_hours": 25},
            headers={"Authorization": f"Bearer {self.student_token}"},
        )
        self.assertEqual(response.status_code, 422)

    def test_sleep_hours_as_string_returns_422(self):
        """A non-numeric sleep_hours must be rejected with 422."""
        response = self.client.put(
            f"/api/student/{self.student_id}/well-being",
            json={"sleep_hours": "eight"},
            headers={"Authorization": f"Bearer {self.student_token}"},
        )
        self.assertEqual(response.status_code, 422)

    def test_online_activity_minutes_as_string_returns_422(self):
        """A non-integer online_activity_minutes must be rejected with 422."""
        response = self.client.put(
            f"/api/student/{self.student_id}/well-being",
            json={"online_activity_minutes": "sixty"},
            headers={"Authorization": f"Bearer {self.student_token}"},
        )
        self.assertEqual(response.status_code, 422)

    def test_invalid_student_uuid_returns_422(self):
        response = self.client.put(
            "/api/student/not-a-uuid/well-being",
            json={"humor": "good"},
            headers={"Authorization": f"Bearer {self.student_token}"},
        )
        self.assertEqual(response.status_code, 422)


class TestWellBeingPutIntegration(unittest.TestCase):
    """Integration tests for PUT /student/{id}/well-being (upsert behaviour)."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

        unique_email = f"wb_put_int_{uuid.uuid4().hex[:8]}@example.com"
        resp = self.client.post(
            "/api/student",
            json=_student_payload(unique_email),
            headers=self.admin_headers,
        )
        self.student_id = resp.json()["user_id"]
        self.student_token = _login_token(self.client, unique_email, "securepass123")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_first_put_creates_record_returns_200(self):
        """First PUT for a student with no record today must return 200 (upsert)."""
        fresh_email = f"wb_fresh_{uuid.uuid4().hex[:8]}@example.com"
        fresh_id, _, fresh_token = _create_student_with_token(
            self.client,
            self.admin_headers,
            fresh_email,
        )

        response = self.client.put(
            f"/api/student/{fresh_id}/well-being",
            json={"humor": "good", "online_activity_minutes": 30, "sleep_hours": 8},
            headers={"Authorization": f"Bearer {fresh_token}"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["humor"], "good")
        self.assertEqual(body["online_activity_minutes"], 30)
        self.assertAlmostEqual(body["sleep_hours"], 8.0, places=1)

    def test_second_put_updates_record_returns_200_no_duplicate(self):
        """Second PUT for the same student and date must update the row and return 200."""
        import asyncio
        import datetime

        from sqlalchemy import func, select

        from md_backend.models.db_models import WellBeing
        from md_backend.utils.database import AsyncSessionLocal

        self.client.put(
            f"/api/student/{self.student_id}/well-being",
            json={"humor": "bad", "online_activity_minutes": 10, "sleep_hours": 5},
            headers={"Authorization": f"Bearer {self.student_token}"},
        )

        response = self.client.put(
            f"/api/student/{self.student_id}/well-being",
            json={"humor": "good", "online_activity_minutes": 120, "sleep_hours": 9},
            headers={"Authorization": f"Bearer {self.student_token}"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["humor"], "good")
        self.assertEqual(body["online_activity_minutes"], 120)
        self.assertAlmostEqual(body["sleep_hours"], 9.0, places=1)

        async def count_rows():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(func.count()).where(
                        WellBeing.student_id == uuid.UUID(self.student_id),
                        WellBeing.date == datetime.date.today(),
                    )
                )
                return result.scalar_one()

        row_count = asyncio.run(count_rows())
        self.assertEqual(row_count, 1, "Upsert must not create duplicate rows")

    def test_put_all_none_fields_is_accepted(self):
        """PUT with all optional fields as null must be accepted."""
        response = self.client.put(
            f"/api/student/{self.student_id}/well-being",
            json={},
            headers={"Authorization": f"Bearer {self.student_token}"},
        )
        self.assertEqual(response.status_code, 200)


class TestWellBeingAuthorizationAndHistory(unittest.TestCase):
    """Authorization and history contract tests for student well-being."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        self.student_id, _, self.student_token = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"wb_auth_student_{uuid.uuid4().hex[:8]}@example.com",
        )
        self.other_student_id, _, self.other_student_token = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"wb_auth_other_student_{uuid.uuid4().hex[:8]}@example.com",
        )
        self.guardian_id, self.guardian_token = _create_guardian_with_token(
            self.client,
            self.admin_headers,
            f"wb_auth_guardian_{uuid.uuid4().hex[:8]}@example.com",
        )
        _, self.other_guardian_token = _create_guardian_with_token(
            self.client,
            self.admin_headers,
            f"wb_auth_other_guardian_{uuid.uuid4().hex[:8]}@example.com",
        )
        _link_guardian_to_student(
            self.client,
            self.admin_headers,
            self.guardian_id,
            self.student_id,
        )

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _seed_well_being(self, student_id: str, day: datetime.date, humor: str) -> None:
        from md_backend.services.student_service import StudentService
        from md_backend.utils.database import AsyncSessionLocal

        async def seed():
            async with AsyncSessionLocal() as session:
                await StudentService().upsert_well_being(
                    session=session,
                    student_id=uuid.UUID(student_id),
                    date=day,
                    humor=humor,
                    online_activity_minutes=30,
                    sleep_hours=8,
                )

        asyncio.run(seed())

    def test_put_is_restricted_to_authenticated_student(self):
        response = self.client.put(
            f"/api/student/{self.student_id}/well-being",
            json={"humor": "good"},
            headers=self._auth_headers(self.student_token),
        )
        self.assertEqual(response.status_code, 200)

        for headers in (
            self.admin_headers,
            self._auth_headers(self.guardian_token),
            self._auth_headers(self.other_student_token),
        ):
            denied = self.client.put(
                f"/api/student/{self.student_id}/well-being",
                json={"humor": "bad"},
                headers=headers,
            )
            self.assertEqual(denied.status_code, 403)

    def test_daily_get_allows_owner_guardian_admin_and_student_today_only(self):
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        self._seed_well_being(self.student_id, today, "good")
        self._seed_well_being(self.student_id, yesterday, "regular")

        allowed_headers = (
            self.admin_headers,
            self._auth_headers(self.guardian_token),
            self._auth_headers(self.student_token),
        )
        for headers in allowed_headers:
            response = self.client.get(
                f"/api/student/{self.student_id}/well-being",
                params={"date": today.isoformat()},
                headers=headers,
            )
            self.assertEqual(response.status_code, 200)

        student_past = self.client.get(
            f"/api/student/{self.student_id}/well-being",
            params={"date": yesterday.isoformat()},
            headers=self._auth_headers(self.student_token),
        )
        self.assertEqual(student_past.status_code, 403)

        other_student = self.client.get(
            f"/api/student/{self.student_id}/well-being",
            params={"date": today.isoformat()},
            headers=self._auth_headers(self.other_student_token),
        )
        self.assertEqual(other_student.status_code, 403)

        other_guardian = self.client.get(
            f"/api/student/{self.student_id}/well-being",
            params={"date": today.isoformat()},
            headers=self._auth_headers(self.other_guardian_token),
        )
        self.assertEqual(other_guardian.status_code, 403)

    def test_history_returns_range_for_owner_guardian(self):
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        self._seed_well_being(self.student_id, yesterday, "bad")
        self._seed_well_being(self.student_id, today, "good")

        response = self.client.get(
            f"/api/student/{self.student_id}/well-being/history",
            params={"from": yesterday.isoformat(), "to": today.isoformat()},
            headers=self._auth_headers(self.guardian_token),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            [item["date"] for item in body], [yesterday.isoformat(), today.isoformat()]
        )
        self.assertEqual([item["humor"] for item in body], ["bad", "good"])

    def test_history_forbids_students_and_non_owner_guardians(self):
        today = datetime.date.today()
        params = {"from": today.isoformat(), "to": today.isoformat()}

        for headers in (
            self._auth_headers(self.student_token),
            self._auth_headers(self.other_student_token),
            self._auth_headers(self.other_guardian_token),
        ):
            response = self.client.get(
                f"/api/student/{self.student_id}/well-being/history",
                params=params,
                headers=headers,
            )
            self.assertEqual(response.status_code, 403)

    class TestStudentCalendar(unittest.TestCase):
        """Integration tests for GET /student/{id}/calendar."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        self.student_id, _, self.student_token = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"calendar_student_{uuid.uuid4().hex[:8]}@example.com",
        )

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def _seed_task(
        self,
        student_id: str,
        title: str,
        date: datetime.datetime,
        deactivated: bool = False,
    ) -> int:
        """Insert a task directly into the DB and return its id."""
        from md_backend.models.db_models import Subject, Task, TaskStatusEnum
        from md_backend.utils.database import AsyncSessionLocal

        async def insert():
            async with AsyncSessionLocal() as session:
                subject_result = await session.execute(
                    select(Subject).limit(1)
                )
                subject = subject_result.scalar_one_or_none()
                if subject is None:
                    subject = Subject(name=f"Subject_{uuid.uuid4().hex[:6]}")
                    session.add(subject)
                    await session.flush()

                task = Task(
                    student_id=uuid.UUID(student_id),
                    title=title,
                    task_status=TaskStatusEnum.PENDING,
                    subject_id=subject.id,
                    date=date,
                    deactivated_at=datetime.datetime.now(datetime.UTC) if deactivated else None,
                )
                session.add(task)
                await session.commit()
                await session.refresh(task)
                return task.id

        return asyncio.run(insert())

    def _this_week_date(self) -> datetime.datetime:
        """Return a datetime in the current week (Wednesday noon UTC)."""
        today = datetime.datetime.now(datetime.UTC)
        days_since_sunday = (today.weekday() + 1) % 7
        sunday = today - datetime.timedelta(days=days_since_sunday)
        wednesday = sunday + datetime.timedelta(days=3)
        return wednesday.replace(hour=12, minute=0, second=0, microsecond=0)

    def _last_week_date(self) -> datetime.datetime:
        """Return a datetime from last week."""
        return self._this_week_date() - datetime.timedelta(days=7)

    def _next_week_date(self) -> datetime.datetime:
        """Return a datetime from next week."""
        return self._this_week_date() + datetime.timedelta(days=7)

    # ------------------------------------------------------------------
    # 200 OK
    # ------------------------------------------------------------------

    def test_returns_200_with_empty_list_when_no_tasks(self):
        response = self.client.get(
            f"/api/student/{self.student_id}/calendar",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_returns_only_current_week_tasks(self):
        self._seed_task(self.student_id, "Esta semana", self._this_week_date())
        self._seed_task(self.student_id, "Semana passada", self._last_week_date())
        self._seed_task(self.student_id, "Próxima semana", self._next_week_date())

        response = self.client.get(
            f"/api/student/{self.student_id}/calendar",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        titles = [t["title"] for t in response.json()]
        self.assertIn("Esta semana", titles)
        self.assertNotIn("Semana passada", titles)
        self.assertNotIn("Próxima semana", titles)

    def test_excludes_deactivated_tasks(self):
        self._seed_task(self.student_id, "Ativa", self._this_week_date())
        self._seed_task(self.student_id, "Desativada", self._this_week_date(), deactivated=True)

        response = self.client.get(
            f"/api/student/{self.student_id}/calendar",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        titles = [t["title"] for t in response.json()]
        self.assertIn("Ativa", titles)
        self.assertNotIn("Desativada", titles)

    def test_response_contains_subject_object(self):
        self._seed_task(self.student_id, "Com matéria", self._this_week_date())

        response = self.client.get(
            f"/api/student/{self.student_id}/calendar",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        tasks = response.json()
        self.assertGreater(len(tasks), 0)
        task = tasks[0]
        self.assertIn("subject", task)
        self.assertIn("id", task["subject"])
        self.assertIn("label", task["subject"])

    def test_response_contains_required_fields(self):
        self._seed_task(self.student_id, "Campos obrigatórios", self._this_week_date())

        response = self.client.get(
            f"/api/student/{self.student_id}/calendar",
            headers=self.admin_headers,
        )
        task = response.json()[0]
        for field in ("id", "date", "title", "status", "subject"):
            self.assertIn(field, task)

    def test_tasks_ordered_by_date_ascending(self):
        monday = self._this_week_date() - datetime.timedelta(days=2)
        friday = self._this_week_date() + datetime.timedelta(days=2)
        self._seed_task(self.student_id, "Sexta", friday)
        self._seed_task(self.student_id, "Segunda", monday)

        response = self.client.get(
            f"/api/student/{self.student_id}/calendar",
            headers=self.admin_headers,
        )
        titles = [t["title"] for t in response.json()]
        segunda_idx = titles.index("Segunda")
        sexta_idx = titles.index("Sexta")
        self.assertLess(segunda_idx, sexta_idx)

    # ------------------------------------------------------------------
    # 403 / 404
    # ------------------------------------------------------------------

    def test_unknown_student_returns_404(self):
        response = self.client.get(
            f"/api/student/{uuid.uuid4()}/calendar",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 404)

    def test_unrelated_student_returns_403(self):
        _, _, other_token = _create_student_with_token(
            self.client,
            self.admin_headers,
            f"calendar_other_{uuid.uuid4().hex[:8]}@example.com",
        )
        response = self.client.get(
            f"/api/student/{self.student_id}/calendar",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_returns_401(self):
        response = self.client.get(f"/api/student/{self.student_id}/calendar")
        self.assertEqual(response.status_code, 401)
