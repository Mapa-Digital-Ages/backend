"""Unit and integration tests for CompanyService and /company router."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import tests.keys_test  # noqa: F401
from md_backend.services.company_service import CompanyService


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
            "/company",
            json=self._payload("create_ok@company.com", spots=80),
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertIn("user_id", body)
        uuid.UUID(body["user_id"])
        self.assertEqual(body["email"], "create_ok@company.com")
        self.assertEqual(body["spots"], 80)
        self.assertEqual(body["available_spots"], 80)
        self.assertNotIn("password", body)
        self.assertNotIn("hashed_password", body)

    def test_create_company_duplicate_email_returns_409(self):
        self.client.post("/company", json=self._payload("company_dup@test.com"))
        resp = self.client.post("/company", json=self._payload("company_dup@test.com"))
        self.assertEqual(resp.status_code, 409)
        self.assertIn("ja cadastrado", resp.json()["detail"].lower())

    def test_create_company_integrity_error_returns_409(self):
        with patch(
            "md_backend.routes.company_router.company_service.create_company",
            new=AsyncMock(side_effect=IntegrityError("forced", {}, Exception("forced"))),
        ):
            resp = self.client.post("/company", json=self._payload("company_integrity@test.com"))

        self.assertEqual(resp.status_code, 409)
        self.assertIn("integridade", resp.json()["detail"].lower())

    def test_create_company_invalid_email_returns_422(self):
        payload = self._payload("not-an-email")
        resp = self.client.post("/company", json=payload)
        self.assertEqual(resp.status_code, 422)

    def test_create_company_missing_required_fields_returns_422(self):
        resp = self.client.post("/company", json={"email": "incomplete@test.com"})
        self.assertEqual(resp.status_code, 422)

    # ------------------------------------------------------------------
    # GET /company
    # ------------------------------------------------------------------

    def test_list_companies(self):
        self.client.post("/company", json=self._payload("company_list_a@test.com"))
        self.client.post("/company", json=self._payload("company_list_b@test.com"))

        resp = self.client.get("/company")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(isinstance(body, list))
        if len(body) > 0:
            for item in body:
                self.assertNotIn("password", item)
                self.assertNotIn("hashed_password", item)

    def test_list_companies_filter_by_name_partial_case_insensitive(self):
        self.client.post(
            "/company",
            json={
                "first_name": "Olimpo",
                "last_name": "Corporate",
                "email": "olimpo_company_filter@test.com",
                "password": "senha1234",
                "spots": 100,
            },
        )

        resp = self.client.get("/company", params={"name": "olimpo"})
        self.assertEqual(resp.status_code, 200)
        items = resp.json()
        self.assertTrue(len(items) >= 1)
        self.assertTrue(any("Olimpo" in item["name"] for item in items))

    # ------------------------------------------------------------------
    # GET /company/{id}
    # ------------------------------------------------------------------

    def test_get_company_by_id_returns_correct_data(self):
        create_resp = self.client.post(
            "/company", json=self._payload("company_getbyid@test.com", spots=42)
        )
        company_id = create_resp.json()["user_id"]

        resp = self.client.get(f"/company/{company_id}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["user_id"], company_id)
        self.assertEqual(body["email"], "company_getbyid@test.com")
        self.assertEqual(body["spots"], 42)
        self.assertEqual(body["available_spots"], 42)
        self.assertNotIn("password", body)

    def test_get_company_by_id_not_found_returns_404(self):
        resp = self.client.get(f"/company/{uuid.uuid4()}")
        self.assertEqual(resp.status_code, 404)

    # ------------------------------------------------------------------
    # PATCH /company/{id}
    # ------------------------------------------------------------------

    def test_update_company_partial_updates_all_fields(self):
        create_resp = self.client.post("/company", json=self._payload("company_upd_full@test.com"))
        company_id = create_resp.json()["user_id"]

        resp = self.client.patch(
            f"/company/{company_id}",
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

    def test_update_company_email_conflict_returns_409(self):
        self.client.post("/company", json=self._payload("company_taken@test.com"))
        create_resp = self.client.post("/company", json=self._payload("company_to_update@test.com"))
        company_id = create_resp.json()["user_id"]

        resp = self.client.patch(
            f"/company/{company_id}",
            json={"email": "company_taken@test.com"},
        )
        self.assertEqual(resp.status_code, 409)

    def test_update_company_not_found_returns_404(self):
        resp = self.client.patch(
            f"/company/{uuid.uuid4()}",
            json={"first_name": "Fantasma"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_update_company_with_phone_and_is_active(self):
        create_resp = self.client.post(
            "/company", json=self._payload("company_phone_active@test.com")
        )
        company_id = create_resp.json()["user_id"]

        # Test is_active = False and phone_number
        resp = self.client.patch(
            f"/company/{company_id}",
            json={"phone_number": "123456789", "is_active": False},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["phone_number"], "123456789")

        # Test is_active = True
        resp2 = self.client.patch(
            f"/company/{company_id}",
            json={"is_active": True},
        )
        self.assertEqual(resp2.status_code, 200)

    def test_update_company_invalid_spots_returns_400(self):
        create_resp = self.client.post(
            "/company", json=self._payload("company_invalid_spots@test.com", spots=10)
        )
        company_id = create_resp.json()["user_id"]

        # Simulate reducing spots below occupied_spots (0). So passing spots = -1
        resp = self.client.patch(
            f"/company/{company_id}",
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

        create_resp = self.client.post("/company", json=self._payload("company_deact@test.com"))
        company_id = create_resp.json()["user_id"]

        resp = self.client.delete(f"/company/{company_id}")
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
        resp = self.client.delete(f"/company/{uuid.uuid4()}")
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
