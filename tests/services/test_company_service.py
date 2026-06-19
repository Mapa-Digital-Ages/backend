"""Unit and integration tests for CompanyService and /company router."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import tests.keys_test  # noqa: F401
from md_backend.models.db_models import (
    PartnershipStatusEnum,
    SchoolCompanyPartnership,
    SponsorshipRequest,
)
from md_backend.services.company_service import CompanyService
from tests.helpers import get_admin_headers


class TestCompanyServiceUnit(unittest.TestCase):
    """Unit tests with a mocked AsyncSession."""

    def test_create_company_returns_none_when_email_exists(self):
        service = CompanyService()

        existing_user = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            service.create_company(
                first_name="Empresa",
                last_name="Duplicada",
                email="dup_unit@test.com",
                password="senha1234",
                spots=10,
                session=mock_session,
            )
        )

        self.assertIsNone(result)
        mock_session.commit.assert_not_called()
        mock_session.flush.assert_not_called()

    def test_list_company_partnerships_excludes_rejected_status(self):
        service = CompanyService()

        company_result = MagicMock()
        company_result.scalar_one_or_none.return_value = MagicMock()

        partnerships_result = MagicMock()
        partnerships_result.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[company_result, partnerships_result])

        result = asyncio.run(service.list_company_partnerships(uuid.uuid4(), mock_session))

        self.assertEqual(result, {"items": [], "total": 0})
        partnership_query = mock_session.execute.await_args_list[1].args[0]
        self.assertIn(
            "school_company_partnership.status !=",
            str(partnership_query),
        )

    def test_list_company_partnerships_can_filter_approved(self):
        service = CompanyService()
        company_id = uuid.uuid4()
        partnership_id = uuid.uuid4()

        company_result = MagicMock()
        company_result.scalar_one_or_none.return_value = MagicMock()

        partnership = MagicMock(spec=SchoolCompanyPartnership)
        partnership.id = partnership_id
        partnership.school_id = uuid.uuid4()
        partnership.company_id = company_id
        partnership.request_id = uuid.uuid4()
        partnership.granted_spots = 3
        partnership.status = PartnershipStatusEnum.APPROVED
        partnership.created_at.isoformat.return_value = "2026-01-01T00:00:00"

        request = MagicMock(spec=SponsorshipRequest)
        request.title = "Pedido aprovado"

        school_user = MagicMock()
        school_user.first_name = "Escola"
        school_user.last_name = "Apoiada"

        partnerships_result = MagicMock()
        partnerships_result.all.return_value = [(partnership, request, school_user)]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[company_result, partnerships_result])

        result = asyncio.run(
            service.list_company_partnerships(
                company_id,
                mock_session,
                status_filter=PartnershipStatusEnum.APPROVED,
            )
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["granted_spots"], 3)
        self.assertNotIn("supported_student_ids", result["items"][0])
        partnership_query = mock_session.execute.await_args_list[1].args[0]
        self.assertIn(
            "school_company_partnership.status =",
            str(partnership_query),
        )

    def test_end_partnership_soft_deletes_partnership_and_frees_spots(self):
        service = CompanyService()
        company_id = uuid.uuid4()
        partnership_id = uuid.uuid4()

        partnership = MagicMock(spec=SchoolCompanyPartnership)
        partnership.id = partnership_id
        partnership.school_id = uuid.uuid4()
        partnership.company_id = company_id
        partnership.request_id = uuid.uuid4()
        partnership.granted_spots = 4
        partnership.status = PartnershipStatusEnum.APPROVED
        partnership.created_at.isoformat.return_value = "2026-01-01T00:00:00"
        partnership.is_active = True
        partnership.deactivated_at = None

        request = MagicMock(spec=SponsorshipRequest)
        request.requested_spots = 10
        request.remaining_spots = 2

        nested_cm = MagicMock()
        nested_cm.__aenter__ = AsyncMock(return_value=None)
        nested_cm.__aexit__ = AsyncMock(return_value=False)

        partnership_result = MagicMock()
        partnership_result.one_or_none.return_value = (partnership, request)

        mock_session = AsyncMock()
        mock_session.begin_nested = MagicMock(return_value=nested_cm)
        mock_session.execute = AsyncMock(side_effect=[partnership_result])

        result = asyncio.run(service.end_partnership(company_id, partnership_id, mock_session))

        self.assertIsNotNone(result)
        self.assertFalse(partnership.is_active)
        self.assertIsNotNone(partnership.deactivated_at)
        self.assertEqual(request.remaining_spots, 6)
        mock_session.commit.assert_awaited_once()


class TestCompanyServiceIntegration(unittest.TestCase):
    """Integration tests against /company via FastAPI TestClient."""

    def setUp(self):
        from fastapi.testclient import TestClient

        from md_backend.main import app

        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def _payload(self, email, spots=10):
        return {
            "first_name": "Empresa",
            "last_name": "Teste",
            "email": email,
            "password": "senha1234",
            "spots": spots,
        }

    # ------------------------------------------------------------------
    # POST /company
    # ------------------------------------------------------------------

    def test_create_company_success_returns_201(self):
        resp = self.client.post(
            "/api/company",
            json=self._payload("create_ok@company.com", spots=80),
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertIn("user_id", body)
        uuid.UUID(body["user_id"])
        self.assertEqual(body["email"], "create_ok@company.com")
        self.assertEqual(body["spots"], 80)

        self.assertNotIn("password", body)
        self.assertNotIn("hashed_password", body)

    def test_create_company_accepts_null_last_name(self):
        from md_backend.models.db_models import UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        email = "company_null_last@test.com"
        resp = self.client.post(
            "/api/company",
            json=self._payload(email) | {"last_name": None},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["name"], "Empresa")

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.email == email)
                )
                return result.scalar_one()

        user = asyncio.run(fetch())
        self.assertIsNone(user.last_name)

    def test_create_company_without_last_name_persists_null(self):
        from md_backend.models.db_models import UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        email = "company_missing_last@test.com"
        payload = self._payload(email)
        del payload["last_name"]
        resp = self.client.post("/api/company", json=payload)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["name"], "Empresa")

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.email == email)
                )
                return result.scalar_one()

        user = asyncio.run(fetch())
        self.assertIsNone(user.last_name)

    def test_created_company_logs_in_with_company_role(self):
        email = "company_role@test.com"
        resp = self.client.post("/api/company", json=self._payload(email, spots=80))
        self.assertEqual(resp.status_code, 201)

        login_resp = self.client.post("/api/login", json={"email": email, "password": "senha1234"})
        self.assertEqual(login_resp.status_code, 200)
        self.assertEqual(login_resp.json()["role"], "company")

    def test_create_company_duplicate_email_returns_409(self):
        self.client.post("/api/company", json=self._payload("company_dup@test.com"))
        resp = self.client.post("/api/company", json=self._payload("company_dup@test.com"))
        self.assertEqual(resp.status_code, 409)
        self.assertIn("ja cadastrado", resp.json()["detail"].lower())

    def test_create_company_integrity_error_returns_409(self):
        with patch(
            "md_backend.routes.company_router.company_service.create_company",
            new=AsyncMock(side_effect=IntegrityError("forced", {}, Exception("forced"))),
        ):
            resp = self.client.post(
                "/api/company", json=self._payload("company_integrity@test.com")
            )

        self.assertEqual(resp.status_code, 409)
        self.assertIn("integridade", resp.json()["detail"].lower())

    def test_create_company_invalid_email_returns_422(self):
        payload = self._payload("not-an-email")
        resp = self.client.post("/api/company", json=payload)
        self.assertEqual(resp.status_code, 422)

    def test_create_company_missing_required_fields_returns_422(self):
        resp = self.client.post("/api/company", json={"email": "incomplete@test.com"})
        self.assertEqual(resp.status_code, 422)

    # ------------------------------------------------------------------
    # GET /company
    # ------------------------------------------------------------------

    def test_list_companies(self):
        self.client.post("/api/company", json=self._payload("company_list_a@test.com"))
        self.client.post("/api/company", json=self._payload("company_list_b@test.com"))

        resp = self.client.get("/api/company")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(isinstance(body, list))
        if len(body) > 0:
            for item in body:
                self.assertNotIn("password", item)
                self.assertNotIn("hashed_password", item)

    def test_list_companies_filter_by_name_partial_case_insensitive(self):
        self.client.post(
            "/api/company",
            json={
                "first_name": "Olimpo",
                "last_name": "Corporate",
                "email": "olimpo_company_filter@test.com",
                "password": "senha1234",
                "spots": 100,
            },
        )

        resp = self.client.get("/api/company", params={"name": "olimpo"})
        self.assertEqual(resp.status_code, 200)
        items = resp.json()
        self.assertTrue(len(items) >= 1)
        self.assertTrue(any("Olimpo" in item["name"] for item in items))

    def test_count_companies_filter_by_name_counts_active_only(self):
        unique_name = f"CountCorp{uuid.uuid4().hex[:8]}"
        lower_name = unique_name.lower()

        active_resp = self.client.post(
            "/api/company",
            json={
                "first_name": unique_name,
                "last_name": "Active",
                "email": f"{lower_name}.active@test.com",
                "password": "senha1234",
                "spots": 20,
            },
        )
        inactive_resp = self.client.post(
            "/api/company",
            json={
                "first_name": unique_name,
                "last_name": "Inactive",
                "email": f"{lower_name}.inactive@test.com",
                "password": "senha1234",
                "spots": 20,
            },
        )
        self.assertEqual(active_resp.status_code, 201)
        self.assertEqual(inactive_resp.status_code, 201)

        inactive_id = inactive_resp.json()["user_id"]
        self.client.delete(f"/api/company/{inactive_id}")

        admin_headers = get_admin_headers(self.client)
        resp = self.client.get(
            "/api/company/count",
            params={"name": lower_name},
            headers=admin_headers,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"total": 1})

    # ------------------------------------------------------------------
    # GET /company/{id}
    # ------------------------------------------------------------------

    def test_get_company_by_id_returns_correct_data(self):
        create_resp = self.client.post(
            "/api/company", json=self._payload("company_getbyid@test.com", spots=42)
        )
        company_id = create_resp.json()["user_id"]

        resp = self.client.get(f"/api/company/{company_id}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["user_id"], company_id)
        self.assertEqual(body["email"], "company_getbyid@test.com")
        self.assertEqual(body["spots"], 42)

        self.assertNotIn("password", body)

    def test_get_company_by_id_not_found_returns_404(self):
        resp = self.client.get(f"/api/company/{uuid.uuid4()}")
        self.assertEqual(resp.status_code, 404)

    # ------------------------------------------------------------------
    # PATCH /company/{id}
    # ------------------------------------------------------------------

    def test_update_company_partial_updates_all_fields(self):
        create_resp = self.client.post(
            "/api/company", json=self._payload("company_upd_full@test.com")
        )
        company_id = create_resp.json()["user_id"]

        resp = self.client.patch(
            f"/api/company/{company_id}",
            json={
                "first_name": "Novo",
                "last_name": "Nome",
                "email": "company_upd_full_new@test.com",
                "spots": 200,
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["email"], "company_upd_full_new@test.com")
        self.assertEqual(body["spots"], 200)
        self.assertEqual(body["name"], "Novo Nome")

    def test_update_company_can_clear_last_name(self):
        from md_backend.models.db_models import UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        create_resp = self.client.post(
            "/api/company", json=self._payload("company_clear_last@test.com")
        )
        company_id = create_resp.json()["user_id"]

        resp = self.client.patch(
            f"/api/company/{company_id}",
            json={"last_name": None},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "Empresa")

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.id == uuid.UUID(company_id))
                )
                return result.scalar_one()

        user = asyncio.run(fetch())
        self.assertIsNone(user.last_name)

    def test_update_company_email_conflict_returns_409(self):
        self.client.post("/api/company", json=self._payload("company_taken@test.com"))
        create_resp = self.client.post(
            "/api/company", json=self._payload("company_to_update@test.com")
        )
        company_id = create_resp.json()["user_id"]

        resp = self.client.patch(
            f"/api/company/{company_id}",
            json={"email": "company_taken@test.com"},
        )
        self.assertEqual(resp.status_code, 409)

    def test_update_company_not_found_returns_404(self):
        resp = self.client.patch(
            f"/api/company/{uuid.uuid4()}",
            json={"first_name": "Fantasma"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_update_company_with_phone_and_is_active(self):
        create_resp = self.client.post(
            "/api/company", json=self._payload("company_phone_active@test.com")
        )
        company_id = create_resp.json()["user_id"]

        # Test is_active = False and phone_number
        resp = self.client.patch(
            f"/api/company/{company_id}",
            json={"phone_number": "123456789", "is_active": False},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["phone_number"], "123456789")

        # Test is_active = True
        resp2 = self.client.patch(
            f"/api/company/{company_id}",
            json={"is_active": True},
        )
        self.assertEqual(resp2.status_code, 200)

    def test_update_company_invalid_spots_returns_400(self):
        create_resp = self.client.post(
            "/api/company", json=self._payload("company_invalid_spots@test.com", spots=10)
        )
        company_id = create_resp.json()["user_id"]

        # Simulate reducing spots below occupied_spots (0). So passing spots = -1
        resp = self.client.patch(
            f"/api/company/{company_id}",
            json={"spots": -1},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Nao e possivel reduzir o total de vagas para", resp.json()["detail"])

    # ------------------------------------------------------------------
    # DELETE /company/{id}
    # ------------------------------------------------------------------

    def test_deactivate_company_sets_is_active_false(self):
        from md_backend.models.db_models import CompanyProfile, UserProfile
        from md_backend.utils.database import AsyncSessionLocal

        create_resp = self.client.post("/api/company", json=self._payload("company_deact@test.com"))
        company_id = create_resp.json()["user_id"]

        resp = self.client.delete(f"/api/company/{company_id}")
        self.assertEqual(resp.status_code, 204)

        async def fetch():
            async with AsyncSessionLocal() as session:
                user_row = await session.execute(
                    select(UserProfile).where(UserProfile.id == uuid.UUID(company_id))
                )
                return user_row.scalar_one()

        user = asyncio.run(fetch())
        self.assertFalse(user.is_active)
        self.assertIsNotNone(user.deactivated_at)

    def test_deactivate_company_not_found_returns_404(self):
        resp = self.client.delete(f"/api/company/{uuid.uuid4()}")
        self.assertEqual(resp.status_code, 404)


class TestCompanyPartnershipsListing(unittest.TestCase):
    """Tests for GET /company/{id}/partnerships and list_company_partnerships."""

    def setUp(self):
        from fastapi.testclient import TestClient

        from md_backend.main import app

        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def _create_company(self, email, spots=50):
        resp = self.client.post(
            "/api/company",
            json={
                "first_name": "Empresa",
                "last_name": "Parc",
                "email": email,
                "password": "senha1234",
                "spots": spots,
            },
        )
        return resp.json()["user_id"]

    def _company_headers(self, email):
        self._create_company(email)
        resp = self.client.post("/api/login", json={"email": email, "password": "senha1234"})
        return {"Authorization": f"Bearer {resp.json()['token']}"}

    def test_list_partnerships_returns_enriched_items(self):
        from md_backend.services.company_service import CompanyService
        from md_backend.services.school_service import SchoolService
        from md_backend.utils.database import AsyncSessionLocal

        async def seed():
            async with AsyncSessionLocal() as session:
                company = await CompanyService().create_company(
                    first_name="Empresa",
                    last_name="Doadora",
                    email="partner_company@test.com",
                    password="senha1234",
                    spots=100,
                    session=session,
                )
                school = await SchoolService().create_school(
                    first_name="Escola",
                    last_name="Beneficiada",
                    email="partner_school@test.com",
                    password="senha1234",
                    is_private=False,
                    session=session,
                )
                request = await SchoolService().create_sponsorship_request(
                    school_id=uuid.UUID(school["user_id"]),
                    title="Apoio 2026",
                    requested_spots=30,
                    session=session,
                )
                await CompanyService().create_partnership(
                    company_id=uuid.UUID(company["user_id"]),
                    request_id=uuid.UUID(request["id"]),
                    granted_spots=10,
                    session=session,
                )
                listed = await CompanyService().list_company_partnerships(
                    uuid.UUID(company["user_id"]),
                    session,
                )
                return company, school, request, listed

        company, school, request, listed = asyncio.run(seed())

        self.assertEqual(listed["total"], 1)
        item = listed["items"][0]
        self.assertEqual(item["company_id"], company["user_id"])
        self.assertEqual(item["school_id"], school["user_id"])
        self.assertEqual(item["school_name"], "Escola Beneficiada")
        self.assertEqual(item["request_title"], "Apoio 2026")
        self.assertEqual(item["request_id"], request["id"])
        self.assertEqual(item["granted_spots"], 10)

    def test_list_partnerships_service_returns_none_for_unknown_company(self):
        from md_backend.services.company_service import CompanyService
        from md_backend.utils.database import AsyncSessionLocal

        async def run():
            async with AsyncSessionLocal() as session:
                return await CompanyService().list_company_partnerships(uuid.uuid4(), session)

        self.assertIsNone(asyncio.run(run()))

    def test_list_partnerships_own_company_returns_200(self):
        email = "partner_self@test.com"
        company_id = self._create_company(email)
        login = self.client.post("/api/login", json={"email": email, "password": "senha1234"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}

        resp = self.client.get(f"/api/company/{company_id}/partnerships", headers=headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 0)
        self.assertEqual(body["items"], [])

    def test_list_partnerships_forbidden_for_other_company(self):
        headers_a = self._company_headers("partner_a@test.com")
        company_b_id = self._create_company("partner_b@test.com")

        resp = self.client.get(f"/api/company/{company_b_id}/partnerships", headers=headers_a)
        self.assertEqual(resp.status_code, 403)

    def test_list_partnerships_not_found_returns_404_for_admin(self):
        admin_headers = get_admin_headers(self.client)
        resp = self.client.get(f"/api/company/{uuid.uuid4()}/partnerships", headers=admin_headers)
        self.assertEqual(resp.status_code, 404)


class TestUpdateCompanyRequestDTO(unittest.TestCase):
    """DTO-level unit tests for UpdateCompanyRequest."""

    def test_update_request_accepts_all_optional(self):
        from md_backend.models.api_models import UpdateCompanyRequest

        req = UpdateCompanyRequest()
        self.assertIsNone(req.first_name)
        self.assertIsNone(req.last_name)
        self.assertIsNone(req.email)
        self.assertIsNone(req.spots)
        self.assertIsNone(req.is_active)

    def test_update_request_validates_email_format(self):
        from pydantic import ValidationError

        from md_backend.models.api_models import UpdateCompanyRequest

        with self.assertRaises(ValidationError):
            UpdateCompanyRequest(email="not-an-email")
