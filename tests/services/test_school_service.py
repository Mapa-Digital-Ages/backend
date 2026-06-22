"""Unit and integration tests for SchoolService and /api/school router."""

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
    """Integration tests against /api/school via FastAPI TestClient."""

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
    # POST /api/school
    # ------------------------------------------------------------------

    def test_create_school_success_returns_201(self):
        resp = self.client.post(
            "/api/school",
            json=self._payload("create_ok@test.com", is_private=False, requested_spots=80),
            headers=self.admin_headers,
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
            "/api/school",
            json=self._payload(email, phone_number="+5511444443333"),
            headers=self.admin_headers,
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
        resp = self.client.post(
            "/api/school", json=self._payload(email), headers=self.admin_headers
        )
        self.assertEqual(resp.status_code, 201)

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.email == email)
                )
                return result.scalar_one()

        user = asyncio.run(fetch())
        self.assertIsNone(user.phone_number)

    def test_create_school_accepts_null_last_name(self):
        from md_backend.models.db_models import UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        email = "school_null_last@test.com"
        resp = self.client.post(
            "/api/school",
            json=self._payload(email) | {"last_name": None},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["name"], "School")

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.email == email)
                )
                return result.scalar_one()

        user = asyncio.run(fetch())
        self.assertIsNone(user.last_name)

    def test_create_school_duplicate_email_returns_409(self):
        self.client.post(
            "/api/school", json=self._payload("school_dup@test.com"), headers=self.admin_headers
        )
        resp = self.client.post(
            "/api/school", json=self._payload("school_dup@test.com"), headers=self.admin_headers
        )
        self.assertEqual(resp.status_code, 409)
        self.assertIn("Email already registered", resp.json()["detail"])

    def test_create_school_integrity_error_returns_409(self):
        with patch(
            "md_backend.routes.school_router.school_service.create_school",
            new=AsyncMock(side_effect=IntegrityError("forced", {}, Exception("forced"))),
        ):
            resp = self.client.post(
                "/api/school",
                json=self._payload("school_integrity@test.com"),
                headers=self.admin_headers,
            )

        self.assertEqual(resp.status_code, 409)
        self.assertIn("integrity", resp.json()["detail"].lower())

    def test_create_school_invalid_email_returns_422(self):
        payload = self._payload("not-an-email")
        resp = self.client.post("/api/school", json=payload, headers=self.admin_headers)
        self.assertEqual(resp.status_code, 422)

    def test_create_school_missing_required_fields_returns_422(self):
        resp = self.client.post(
            "/api/school", json={"email": "incomplete@test.com"}, headers=self.admin_headers
        )
        self.assertEqual(resp.status_code, 422)

    def test_create_school_unauthenticated_returns_401(self):
        resp = self.client.post("/api/school", json=self._payload("school_unauth@test.com"))
        self.assertEqual(resp.status_code, 401)

    def test_create_school_non_superadmin_returns_403(self):
        from tests.helpers import create_approved_user

        token = create_approved_user(
            self.client, self.admin_headers, "school_create_nonadmin@test.com"
        )
        resp = self.client.post(
            "/api/school",
            json=self._payload("school_create_forbidden@test.com"),
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 403)

    # ------------------------------------------------------------------
    # GET /api/school
    # ------------------------------------------------------------------

    def test_list_schools_returns_pagination_envelope(self):
        self.client.post(
            "/api/school", json=self._payload("school_list_a@test.com"), headers=self.admin_headers
        )
        self.client.post(
            "/api/school", json=self._payload("school_list_b@test.com"), headers=self.admin_headers
        )

        resp = self.client.get("/api/school", headers=self.admin_headers)
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
            "/api/school",
            json={
                "first_name": "Olympus",
                "last_name": "Education",
                "email": "olympus_filter@test.com",
                "password": "password1234",
                "is_private": False,
                "requested_spots": 100,
            },
            headers=self.admin_headers,
        )

        resp = self.client.get(
            "/api/school", params={"name": "olympus"}, headers=self.admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertTrue(len(items) >= 1)
        self.assertTrue(any("Olympus" in item["name"] for item in items))

    def test_list_schools_pagination_respects_size_and_page(self):
        resp = self.client.get(
            "/api/school", params={"page": 1, "size": 1}, headers=self.admin_headers
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["size"], 1)
        self.assertLessEqual(len(body["items"]), 1)

    def test_list_schools_unauthenticated_returns_401(self):
        resp = self.client.get("/api/school")
        self.assertEqual(resp.status_code, 401)

    # ------------------------------------------------------------------
    # GET /api/school/{id}
    # ------------------------------------------------------------------

    def test_get_school_by_id_returns_correct_data(self):
        create_resp = self.client.post(
            "/api/school",
            json=self._payload("school_getbyid@test.com", requested_spots=42),
            headers=self.admin_headers,
        )
        school_id = create_resp.json()["user_id"]

        resp = self.client.get(f"/api/school/{school_id}", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["user_id"], school_id)
        self.assertEqual(body["email"], "school_getbyid@test.com")
        self.assertEqual(body["requested_spots"], 42)
        self.assertEqual(body["student_count"], 0)
        self.assertNotIn("password", body)

    def test_get_school_by_id_not_found_returns_404(self):
        resp = self.client.get(f"/api/school/{uuid.uuid4()}", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 404)

    def test_get_school_by_id_unauthenticated_returns_401(self):
        resp = self.client.get(f"/api/school/{uuid.uuid4()}")
        self.assertEqual(resp.status_code, 401)

    # ------------------------------------------------------------------
    # PATCH /api/school/{id}
    # ------------------------------------------------------------------

    def test_update_school_partial_updates_all_fields(self):
        create_resp = self.client.post(
            "/api/school",
            json=self._payload("school_upd_full@test.com"),
            headers=self.admin_headers,
        )
        school_id = create_resp.json()["user_id"]

        resp = self.client.patch(
            f"/api/school/{school_id}",
            json={
                "first_name": "New",
                "last_name": "Name",
                "email": "school_upd_full_new@test.com",
                "is_private": False,
            },
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["email"], "school_upd_full_new@test.com")
        self.assertEqual(body["is_private"], False)
        self.assertEqual(body["name"], "New Name")

    def test_update_school_can_clear_last_name(self):
        from md_backend.models.db_models import UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        create_resp = self.client.post(
            "/api/school",
            json=self._payload("school_clear_last@test.com"),
            headers=self.admin_headers,
        )
        school_id = create_resp.json()["user_id"]

        resp = self.client.patch(
            f"/api/school/{school_id}",
            json={"last_name": None},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "School")

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.id == uuid.UUID(school_id))
                )
                return result.scalar_one()

        user = asyncio.run(fetch())
        self.assertIsNone(user.last_name)

    def test_update_school_email_conflict_returns_409(self):
        self.client.post(
            "/api/school",
            json=self._payload("school_taken@test.com"),
            headers=self.admin_headers,
        )
        create_resp = self.client.post(
            "/api/school",
            json=self._payload("school_to_update@test.com"),
            headers=self.admin_headers,
        )
        school_id = create_resp.json()["user_id"]

        resp = self.client.patch(
            f"/api/school/{school_id}",
            json={"email": "school_taken@test.com"},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 409)

    def test_update_school_not_found_returns_404(self):
        resp = self.client.patch(
            f"/api/school/{uuid.uuid4()}",
            json={"first_name": "Ghost"},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_update_school_unauthenticated_returns_401(self):
        resp = self.client.patch(
            f"/api/school/{uuid.uuid4()}",
            json={"first_name": "X"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_update_school_non_superadmin_returns_403(self):
        from tests.helpers import create_approved_user

        token = create_approved_user(
            self.client, self.admin_headers, "school_patch_nonadmin@test.com"
        )
        resp = self.client.patch(
            f"/api/school/{uuid.uuid4()}",
            json={"first_name": "X"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 403)

    # ------------------------------------------------------------------
    # DELETE /api/school/{id}
    # ------------------------------------------------------------------

    def test_deactivate_school_sets_is_active_false(self):
        from md_backend.models.db_models import SchoolProfile, UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        create_resp = self.client.post(
            "/api/school",
            json=self._payload("school_deact@test.com"),
            headers=self.admin_headers,
        )
        school_id = create_resp.json()["user_id"]

        resp = self.client.delete(f"/api/school/{school_id}", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 204)

        async def fetch():
            async with AsyncSessionLocal() as session:
                user_row = await session.execute(
                    select(UserProfile).where(UserProfile.id == uuid.UUID(school_id))
                )
                school_row = await session.execute(
                    select(SchoolProfile).where(SchoolProfile.user_id == uuid.UUID(school_id))
                )
                return user_row.scalar_one(), school_row.scalar_one()

        user, school = asyncio.run(fetch())
        self.assertFalse(user.is_active)
        self.assertIsNotNone(user.deactivated_at)
        self.assertIsNotNone(school.deactivated_at)

    def test_deactivate_school_not_found_returns_404(self):
        resp = self.client.delete(f"/api/school/{uuid.uuid4()}", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 404)

    def test_deactivate_school_unauthenticated_returns_401(self):
        resp = self.client.delete(f"/api/school/{uuid.uuid4()}")
        self.assertEqual(resp.status_code, 401)

    def test_deactivate_school_non_superadmin_returns_403(self):
        from tests.helpers import create_approved_user

        token = create_approved_user(
            self.client, self.admin_headers, "school_delete_nonadmin@test.com"
        )
        resp = self.client.delete(
            f"/api/school/{uuid.uuid4()}",
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

    def test_update_request_validates_email_format(self):
        from pydantic import ValidationError

        from md_backend.models.api_models import UpdateSchoolRequest

        with self.assertRaises(ValidationError):
            UpdateSchoolRequest(email="not-an-email")


class TestSponsorshipRequestIntegration(unittest.TestCase):
    """Integration tests for POST and GET /api/school/{id}/requests."""

    def setUp(self):
        from fastapi.testclient import TestClient

        from md_backend.main import app
        from tests.helpers import get_admin_headers

        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

        # Create a school and get its credentials
        school_email = f"school_req_{uuid.uuid4().hex[:8]}@test.com"
        school_password = "password1234"
        resp = self.client.post(
            "/api/school",
            json={
                "first_name": "Request",
                "last_name": "School",
                "email": school_email,
                "password": school_password,
                "is_private": False,
            },
            headers=self.admin_headers,
        )
        self.school_id = resp.json()["user_id"]

        login_resp = self.client.post(
            "/api/login", json={"email": school_email, "password": school_password}
        )
        self.school_headers = {"Authorization": f"Bearer {login_resp.json()['token']}"}

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    # POST /api/school/{id}/requests
    def test_create_request_returns_201_with_open_status(self):
        resp = self.client.post(
            f"/api/school/{self.school_id}/requests",
            json={"title": "Pedido de bolsas", "requested_spots": 50},
            headers=self.school_headers,
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["status"], "open")
        self.assertEqual(body["requested_spots"], 50)

    def test_create_request_remaining_spots_equals_requested_spots(self):
        """Validate business rule: remaining_spots must be initialized to requested_spots."""
        resp = self.client.post(
            f"/api/school/{self.school_id}/requests",
            json={"title": "Pedido de bolsas", "requested_spots": 30},
            headers=self.school_headers,
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["remaining_spots"], body["requested_spots"])
        self.assertEqual(body["remaining_spots"], 30)

    def test_create_request_status_is_open_on_creation(self):
        """Validate business rule: status must be OPEN on creation."""
        from md_backend.models.db_models import SponsorshipRequest
        from md_backend.utils.database import AsyncSessionLocal

        resp = self.client.post(
            f"/api/school/{self.school_id}/requests",
            json={"title": "Pedido de bolsas", "requested_spots": 10},
            headers=self.school_headers,
        )
        self.assertEqual(resp.status_code, 201)
        request_id = resp.json()["id"]

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(SponsorshipRequest).where(SponsorshipRequest.id == uuid.UUID(request_id))
                )
                return result.scalar_one()

        db_record = asyncio.run(fetch())
        from md_backend.models.db_models import SponsorshipRequestStatusEnum

        self.assertEqual(db_record.status, SponsorshipRequestStatusEnum.OPEN)
        self.assertEqual(db_record.remaining_spots, db_record.requested_spots)

    def test_create_request_admin_can_create_for_any_school(self):
        resp = self.client.post(
            f"/api/school/{self.school_id}/requests",
            json={"title": "Pedido de bolsas", "requested_spots": 20},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 201)

    def test_create_request_other_user_returns_403(self):
        from tests.helpers import create_approved_user

        token = create_approved_user(
            self.client, self.admin_headers, f"other_{uuid.uuid4().hex[:8]}@test.com"
        )
        resp = self.client.post(
            f"/api/school/{self.school_id}/requests",
            json={"title": "Pedido de bolsas", "requested_spots": 10},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_create_request_unauthenticated_returns_401(self):
        resp = self.client.post(
            f"/api/school/{self.school_id}/requests",
            json={"title": "Pedido de bolsas", "requested_spots": 10},
        )
        self.assertEqual(resp.status_code, 401)

    def test_create_request_school_not_found_returns_404(self):
        resp = self.client.post(
            f"/api/school/{uuid.uuid4()}/requests",
            json={"title": "Pedido de bolsas", "requested_spots": 10},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_create_request_invalid_spots_returns_422(self):
        resp = self.client.post(
            f"/api/school/{self.school_id}/requests",
            json={"title": "Pedido de bolsas", "requested_spots": 0},
            headers=self.school_headers,
        )
        self.assertEqual(resp.status_code, 422)

    # GET /api/school/{id}/requests
    def test_list_requests_returns_all_school_requests(self):
        self.client.post(
            f"/api/school/{self.school_id}/requests",
            json={"title": "Pedido de bolsas A", "requested_spots": 10},
            headers=self.school_headers,
        )
        self.client.post(
            f"/api/school/{self.school_id}/requests",
            json={"title": "Pedido de bolsas B", "requested_spots": 20},
            headers=self.school_headers,
        )

        resp = self.client.get(
            f"/api/school/{self.school_id}/requests",
            headers=self.school_headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("items", body)
        self.assertIn("total", body)
        self.assertGreaterEqual(body["total"], 2)

    def test_list_requests_shows_progress_fields(self):
        self.client.post(
            f"/api/school/{self.school_id}/requests",
            json={"title": "Pedido de bolsas", "requested_spots": 40},
            headers=self.school_headers,
        )

        resp = self.client.get(
            f"/api/school/{self.school_id}/requests",
            headers=self.school_headers,
        )
        self.assertEqual(resp.status_code, 200)
        item = resp.json()["items"][0]
        self.assertIn("requested_spots", item)
        self.assertIn("remaining_spots", item)
        self.assertIn("status", item)

    def test_list_requests_admin_can_list_any_school(self):
        resp = self.client.get(
            f"/api/school/{self.school_id}/requests",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)

    def test_list_requests_other_user_returns_403(self):
        from tests.helpers import create_approved_user

        token = create_approved_user(
            self.client, self.admin_headers, f"other2_{uuid.uuid4().hex[:8]}@test.com"
        )
        resp = self.client.get(
            f"/api/school/{self.school_id}/requests",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_list_requests_unauthenticated_returns_401(self):
        resp = self.client.get(f"/api/school/{self.school_id}/requests")
        self.assertEqual(resp.status_code, 401)

    def test_list_requests_school_not_found_returns_404(self):
        resp = self.client.get(
            f"/api/school/{uuid.uuid4()}/requests",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)


class TestPartnershipIntegration(unittest.TestCase):
    """Integration tests for POST /api/company/{id}/partnerships and GET /api/company/requests."""

    def setUp(self):
        from fastapi.testclient import TestClient

        from md_backend.main import app
        from tests.helpers import get_admin_headers

        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

        # Create school
        school_email = f"school_partner_{uuid.uuid4().hex[:8]}@test.com"
        school_password = "password1234"
        school_resp = self.client.post(
            "/api/school",
            json={
                "first_name": "Partner",
                "last_name": "School",
                "email": school_email,
                "password": school_password,
                "is_private": False,
            },
            headers=self.admin_headers,
        )
        self.school_id = school_resp.json()["user_id"]
        school_login = self.client.post(
            "/api/login", json={"email": school_email, "password": school_password}
        )
        self.school_headers = {"Authorization": f"Bearer {school_login.json()['token']}"}

        # Create sponsorship request with 10 spots
        req_resp = self.client.post(
            f"/api/school/{self.school_id}/requests",
            json={"title": "Pedido de bolsas", "requested_spots": 10},
            headers=self.school_headers,
        )
        self.request_id = req_resp.json()["id"]

        # Create company A
        company_a_email = f"company_a_{uuid.uuid4().hex[:8]}@test.com"
        company_a_password = "password1234"
        company_a_resp = self.client.post(
            "/api/company",
            json={
                "first_name": "Company",
                "last_name": "Alpha",
                "email": company_a_email,
                "password": company_a_password,
                "spots": 100,
            },
            headers=self.admin_headers,
        )
        self.company_a_id = company_a_resp.json()["user_id"]
        login_a = self.client.post(
            "/api/login", json={"email": company_a_email, "password": company_a_password}
        )
        self.company_a_headers = {"Authorization": f"Bearer {login_a.json()['token']}"}

        # Create company B
        company_b_email = f"company_b_{uuid.uuid4().hex[:8]}@test.com"
        company_b_password = "password1234"
        company_b_resp = self.client.post(
            "/api/company",
            json={
                "first_name": "Company",
                "last_name": "Beta",
                "email": company_b_email,
                "password": company_b_password,
                "spots": 100,
            },
            headers=self.admin_headers,
        )
        self.company_b_id = company_b_resp.json()["user_id"]
        login_b = self.client.post(
            "/api/login", json={"email": company_b_email, "password": company_b_password}
        )
        self.company_b_headers = {"Authorization": f"Bearer {login_b.json()['token']}"}

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    # POST /api/company/{id}/partnerships
    def test_create_partnership_returns_201_with_pending_status(self):
        resp = self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 5},
            headers=self.company_a_headers,
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["granted_spots"], 5)
        self.assertEqual(body["company_id"], self.company_a_id)

    def test_create_partnership_reduces_remaining_spots(self):
        self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 4},
            headers=self.company_a_headers,
        )
        showcase = self.client.get("/api/company/requests")
        items = showcase.json()["items"]
        req = next(i for i in items if i["id"] == self.request_id)
        self.assertEqual(req["remaining_spots"], 6)

    def test_create_partnership_overbooking_returns_400(self):
        """Two companies trying to donate beyond available spots — second must get 400."""
        # Company A donates 7 (leaves 3)
        resp_a = self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 7},
            headers=self.company_a_headers,
        )
        self.assertEqual(resp_a.status_code, 201)

        # Company B tries to donate 5 — only 3 remain — must be blocked
        resp_b = self.client.post(
            f"/api/company/{self.company_b_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 5},
            headers=self.company_b_headers,
        )
        self.assertEqual(resp_b.status_code, 400)
        self.assertIn("remaining", resp_b.json()["detail"].lower())

    def test_create_partnership_exact_spots_marks_request_fulfilled(self):
        """Donating exactly remaining_spots should mark the request as fulfilled."""
        from md_backend.models.db_models import SponsorshipRequest, SponsorshipRequestStatusEnum
        from md_backend.utils.database import AsyncSessionLocal

        resp = self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 10},
            headers=self.company_a_headers,
        )
        self.assertEqual(resp.status_code, 201)

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(SponsorshipRequest).where(
                        SponsorshipRequest.id == uuid.UUID(self.request_id)
                    )
                )
                return result.scalar_one()

        req = asyncio.run(fetch())
        self.assertEqual(req.status, SponsorshipRequestStatusEnum.FULFILLED)
        self.assertEqual(req.remaining_spots, 0)

    def test_create_partnership_partial_donation_marks_partially_fulfilled(self):
        """Donating fewer than remaining_spots should mark the request as partially_fulfilled."""
        from md_backend.models.db_models import SponsorshipRequest, SponsorshipRequestStatusEnum
        from md_backend.utils.database import AsyncSessionLocal

        resp = self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 3},
            headers=self.company_a_headers,
        )
        self.assertEqual(resp.status_code, 201)

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(SponsorshipRequest).where(
                        SponsorshipRequest.id == uuid.UUID(self.request_id)
                    )
                )
                return result.scalar_one()

        req = asyncio.run(fetch())
        self.assertEqual(req.status, SponsorshipRequestStatusEnum.PARTIALLY_FULFILLED)
        self.assertEqual(req.remaining_spots, 7)

    def test_create_partnership_unauthenticated_returns_401(self):
        resp = self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 1},
        )
        self.assertEqual(resp.status_code, 401)

    def test_create_partnership_other_user_returns_403(self):
        resp = self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 1},
            headers=self.company_b_headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_create_partnership_invalid_request_id_returns_404(self):
        resp = self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": str(uuid.uuid4()), "granted_spots": 1},
            headers=self.company_a_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_create_partnership_zero_granted_spots_returns_422(self):
        resp = self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 0},
            headers=self.company_a_headers,
        )
        self.assertEqual(resp.status_code, 422)

    # GET /api/company/requests  (vitrine pública)
    def test_showcase_returns_open_requests(self):
        resp = self.client.get("/api/company/requests")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("items", body)
        self.assertIn("total", body)
        ids = [i["id"] for i in body["items"]]
        self.assertIn(self.request_id, ids)

    def test_showcase_exposes_remaining_spots(self):
        resp = self.client.get("/api/company/requests")
        items = resp.json()["items"]
        req = next(i for i in items if i["id"] == self.request_id)
        self.assertIn("remaining_spots", req)
        self.assertEqual(req["remaining_spots"], 10)

    def test_showcase_does_not_return_fulfilled_requests(self):
        # Fulfill the request completely
        self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 10},
            headers=self.company_a_headers,
        )
        resp = self.client.get("/api/company/requests")
        ids = [i["id"] for i in resp.json()["items"]]
        self.assertNotIn(self.request_id, ids)

    def test_showcase_returns_partially_fulfilled_requests(self):
        self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 3},
            headers=self.company_a_headers,
        )
        resp = self.client.get("/api/company/requests")
        items = resp.json()["items"]
        req = next((i for i in items if i["id"] == self.request_id), None)
        self.assertIsNotNone(req)

    def test_showcase_no_auth_required(self):
        """Vitrine is public — no token needed."""
        resp = self.client.get("/api/company/requests")
        self.assertEqual(resp.status_code, 200)

    # GET /api/school/{id}/partnerships
    def test_list_school_partnerships_returns_pending_with_company_name(self):
        self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 4},
            headers=self.company_a_headers,
        )
        resp = self.client.get(
            f"/api/school/{self.school_id}/partnerships",
            headers=self.school_headers,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 1)
        item = body["items"][0]
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["granted_spots"], 4)
        self.assertEqual(item["company_id"], self.company_a_id)
        self.assertEqual(item["company_name"], "Company Alpha")
        self.assertEqual(item["request_id"], self.request_id)
        self.assertEqual(item["request_title"], "Pedido de bolsas")

    def test_partial_acceptance_keeps_request_open_and_shows_partnership(self):
        """School asks 10, company takes 4: request keeps 6 open AND a partnership card exists."""
        self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 4},
            headers=self.company_a_headers,
        )

        requests = self.client.get(
            f"/api/school/{self.school_id}/requests",
            headers=self.school_headers,
        ).json()["items"]
        req = next(i for i in requests if i["id"] == self.request_id)
        self.assertEqual(req["remaining_spots"], 6)
        self.assertEqual(req["status"], "partially_fulfilled")

        partnerships = self.client.get(
            f"/api/school/{self.school_id}/partnerships",
            headers=self.school_headers,
        ).json()["items"]
        self.assertEqual(len(partnerships), 1)
        self.assertEqual(partnerships[0]["granted_spots"], 4)

    def test_list_school_partnerships_status_filter(self):
        self.client.post(
            f"/api/company/{self.company_a_id}/partnerships",
            json={"request_id": self.request_id, "granted_spots": 4},
            headers=self.company_a_headers,
        )
        pending = self.client.get(
            f"/api/school/{self.school_id}/partnerships",
            params={"partnership_status": "pending"},
            headers=self.school_headers,
        )
        self.assertEqual(pending.json()["total"], 1)

        approved = self.client.get(
            f"/api/school/{self.school_id}/partnerships",
            params={"partnership_status": "approved"},
            headers=self.school_headers,
        )
        self.assertEqual(approved.json()["total"], 0)

    def test_list_school_partnerships_invalid_status_returns_422(self):
        resp = self.client.get(
            f"/api/school/{self.school_id}/partnerships",
            params={"partnership_status": "bogus"},
            headers=self.school_headers,
        )
        self.assertEqual(resp.status_code, 422)

    def test_list_school_partnerships_other_user_returns_403(self):
        resp = self.client.get(
            f"/api/school/{self.school_id}/partnerships",
            headers=self.company_a_headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_list_school_partnerships_unauthenticated_returns_401(self):
        resp = self.client.get(f"/api/school/{self.school_id}/partnerships")
        self.assertEqual(resp.status_code, 401)

    def test_list_school_partnerships_school_not_found_returns_404(self):
        resp = self.client.get(
            f"/api/school/{uuid.uuid4()}/partnerships",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)
