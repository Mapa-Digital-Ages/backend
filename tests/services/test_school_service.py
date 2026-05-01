"""Unit and integration tests for SchoolService and /school router."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import tests.keys_test  # noqa: F401
from md_backend.services.school_service import SchoolService


class TestSchoolServiceUnit(unittest.TestCase):
    """Unit tests with a mocked AsyncSession."""

    def test_create_school_returns_none_when_email_exists(self):
        service = SchoolService()

        existing_user = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            service.create_school(
                first_name="School",
                last_name="Duplicate",
                email="dup_unit@test.com",
                password="password1234",
                is_private=True,
                session=mock_session,
            )
        )

        self.assertIsNone(result)
        mock_session.commit.assert_not_called()
        mock_session.refresh.assert_not_called()


class TestSchoolServiceIntegration(unittest.TestCase):
    """Integration tests against /school via FastAPI TestClient."""

    def setUp(self):
        from fastapi.testclient import TestClient

        from md_backend.main import app
        from tests.helpers import get_admin_headers

        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def _payload(self, email, *, is_private=True, requested_spots=None, phone_number=None):
        payload = {
            "first_name": "School",
            "last_name": "Test",
            "email": email,
            "password": "password1234",
            "is_private": is_private,
            "requested_spots": requested_spots,
        }
        if phone_number is not None:
            payload["phone_number"] = phone_number
        return payload

    # ------------------------------------------------------------------
    # POST /school
    # ------------------------------------------------------------------

    def test_create_school_success_returns_201(self):
        resp = self.client.post(
            "/school",
            json=self._payload("create_ok@test.com", is_private=False, requested_spots=80),
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertIn("user_id", body)
        uuid.UUID(body["user_id"])
        self.assertEqual(body["email"], "create_ok@test.com")
        self.assertEqual(body["is_private"], False)
        self.assertEqual(body["requested_spots"], 80)
        self.assertEqual(body["student_count"], 0)
        self.assertTrue(body["is_active"])
        self.assertIsNone(body["deactivated_at"])
        self.assertNotIn("password", body)
        self.assertNotIn("hashed_password", body)

    def test_create_school_with_phone_number_persists(self):
        from md_backend.models.db_models import UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        email = "school_phone@test.com"
        resp = self.client.post(
            "/school", json=self._payload(email, phone_number="+5511444443333")
        )
        self.assertEqual(resp.status_code, 201)

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.email == email)
                )
                return result.scalar_one()

        user = asyncio.run(fetch())
        self.assertEqual(user.phone_number, "+5511444443333")

    def test_create_school_without_phone_number_persists_null(self):
        from md_backend.models.db_models import UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        email = "school_no_phone@test.com"
        resp = self.client.post("/school", json=self._payload(email))
        self.assertEqual(resp.status_code, 201)

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.email == email)
                )
                return result.scalar_one()

        user = asyncio.run(fetch())
        self.assertIsNone(user.phone_number)

    def test_create_school_duplicate_email_returns_409(self):
        self.client.post("/school", json=self._payload("school_dup@test.com"))
        resp = self.client.post("/school", json=self._payload("school_dup@test.com"))
        self.assertEqual(resp.status_code, 409)
        self.assertIn("Email already registered", resp.json()["detail"])

    def test_create_school_integrity_error_returns_409(self):
        with patch(
            "md_backend.routes.school_router.school_service.create_school",
            new=AsyncMock(side_effect=IntegrityError("forced", {}, Exception("forced"))),
        ):
            resp = self.client.post(
                "/school", json=self._payload("school_integrity@test.com")
            )

        self.assertEqual(resp.status_code, 409)
        self.assertIn("integrity", resp.json()["detail"].lower())

    def test_create_school_invalid_email_returns_422(self):
        payload = self._payload("not-an-email")
        resp = self.client.post("/school", json=payload)
        self.assertEqual(resp.status_code, 422)

    def test_create_school_missing_required_fields_returns_422(self):
        resp = self.client.post("/school", json={"email": "incomplete@test.com"})
        self.assertEqual(resp.status_code, 422)

    # ------------------------------------------------------------------
    # GET /school
    # ------------------------------------------------------------------

    def test_list_schools_returns_pagination_envelope(self):
        self.client.post("/school", json=self._payload("school_list_a@test.com"))
        self.client.post("/school", json=self._payload("school_list_b@test.com"))

        resp = self.client.get("/school")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("items", body)
        self.assertIn("total", body)
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["size"], 20)
        for item in body["items"]:
            self.assertNotIn("password", item)
            self.assertNotIn("hashed_password", item)

    def test_list_schools_filter_by_name_partial_case_insensitive(self):
        self.client.post(
            "/school",
            json={
                "first_name": "Olympus",
                "last_name": "Education",
                "email": "olympus_filter@test.com",
                "password": "password1234",
                "is_private": False,
                "requested_spots": 100,
            },
        )

        resp = self.client.get("/school", params={"name": "olympus"})
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertTrue(len(items) >= 1)
        self.assertTrue(any("Olympus" in item["name"] for item in items))

    def test_list_schools_pagination_respects_size_and_page(self):
        resp = self.client.get("/school", params={"page": 1, "size": 1})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["size"], 1)
        self.assertLessEqual(len(body["items"]), 1)

    # ------------------------------------------------------------------
    # GET /school/{id}
    # ------------------------------------------------------------------

    def test_get_school_by_id_returns_correct_data(self):
        create_resp = self.client.post(
            "/school", json=self._payload("school_getbyid@test.com", requested_spots=42)
        )
        school_id = create_resp.json()["user_id"]

        resp = self.client.get(f"/school/{school_id}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["user_id"], school_id)
        self.assertEqual(body["email"], "school_getbyid@test.com")
        self.assertEqual(body["requested_spots"], 42)
        self.assertEqual(body["student_count"], 0)
        self.assertNotIn("password", body)

    def test_get_school_by_id_not_found_returns_404(self):
        resp = self.client.get(f"/school/{uuid.uuid4()}")
        self.assertEqual(resp.status_code, 404)

    # ------------------------------------------------------------------
    # PATCH /school/{id}
    # ------------------------------------------------------------------

    def test_update_school_partial_updates_all_fields(self):
        create_resp = self.client.post(
            "/school", json=self._payload("school_upd_full@test.com")
        )
        school_id = create_resp.json()["user_id"]

        resp = self.client.patch(
            f"/school/{school_id}",
            json={
                "first_name": "New",
                "last_name": "Name",
                "email": "school_upd_full_new@test.com",
                "is_private": False,
                "requested_spots": 200,
            },
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["email"], "school_upd_full_new@test.com")
        self.assertEqual(body["is_private"], False)
        self.assertEqual(body["requested_spots"], 200)
        self.assertEqual(body["name"], "New Name")

    def test_update_school_email_conflict_returns_409(self):
        self.client.post("/school", json=self._payload("school_taken@test.com"))
        create_resp = self.client.post(
            "/school", json=self._payload("school_to_update@test.com")
        )
        school_id = create_resp.json()["user_id"]

        resp = self.client.patch(
            f"/school/{school_id}",
            json={"email": "school_taken@test.com"},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 409)

    def test_update_school_not_found_returns_404(self):
        resp = self.client.patch(
            f"/school/{uuid.uuid4()}",
            json={"first_name": "Ghost"},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_update_school_unauthenticated_returns_401(self):
        resp = self.client.patch(
            f"/school/{uuid.uuid4()}",
            json={"first_name": "X"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_update_school_non_superadmin_returns_403(self):
        from tests.helpers import create_approved_user

        token = create_approved_user(
            self.client, self.admin_headers, "school_patch_nonadmin@test.com"
        )
        resp = self.client.patch(
            f"/school/{uuid.uuid4()}",
            json={"first_name": "X"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 403)

    # ------------------------------------------------------------------
    # DELETE /school/{id}
    # ------------------------------------------------------------------

    def test_deactivate_school_sets_is_active_false(self):
        from md_backend.models.db_models import SchoolProfile, UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        create_resp = self.client.post(
            "/school", json=self._payload("school_deact@test.com")
        )
        school_id = create_resp.json()["user_id"]

        resp = self.client.delete(f"/school/{school_id}", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 204)

        async def fetch():
            async with AsyncSessionLocal() as session:
                user_row = await session.execute(
                    select(UserProfile).where(UserProfile.id == uuid.UUID(school_id))
                )
                school_row = await session.execute(
                    select(SchoolProfile).where(
                        SchoolProfile.user_id == uuid.UUID(school_id)
                    )
                )
                return user_row.scalar_one(), school_row.scalar_one()

        user, school = asyncio.run(fetch())
        self.assertFalse(user.is_active)
        self.assertIsNotNone(user.deactivated_at)
        self.assertIsNotNone(school.deactivated_at)

    def test_deactivate_school_not_found_returns_404(self):
        resp = self.client.delete(
            f"/school/{uuid.uuid4()}", headers=self.admin_headers
        )
        self.assertEqual(resp.status_code, 404)

    def test_deactivate_school_unauthenticated_returns_401(self):
        resp = self.client.delete(f"/school/{uuid.uuid4()}")
        self.assertEqual(resp.status_code, 401)

    def test_deactivate_school_non_superadmin_returns_403(self):
        from tests.helpers import create_approved_user

        token = create_approved_user(
            self.client, self.admin_headers, "school_delete_nonadmin@test.com"
        )
        resp = self.client.delete(
            f"/school/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 403)


class TestUpdateSchoolRequestDTO(unittest.TestCase):
    """DTO-level unit tests for UpdateSchoolRequest."""

    def test_update_request_accepts_all_optional(self):
        from md_backend.models.api_models import UpdateSchoolRequest

        req = UpdateSchoolRequest()
        self.assertIsNone(req.first_name)
        self.assertIsNone(req.last_name)
        self.assertIsNone(req.email)
        self.assertIsNone(req.is_private)
        self.assertIsNone(req.requested_spots)

    def test_update_request_validates_email_format(self):
        from pydantic import ValidationError

        from md_backend.models.api_models import UpdateSchoolRequest

        with self.assertRaises(ValidationError):
            UpdateSchoolRequest(email="not-an-email")
