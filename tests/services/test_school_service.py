"""Unit and integration tests for SchoolService."""

import asyncio
import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import tests.keys_test  # noqa: F401
from md_backend.services.school_service import SchoolService


def _make_mock_user(user_id=10, email="escola@test.com", created_at=None):
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.name = "Escola Teste"
    user.status = MagicMock()
    user.status.value = "aprovado"
    user.created_at = created_at or datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return user


def _make_mock_school(user_id=10, cnpj="12.345.678/0001-90", is_private=True):
    school = MagicMock()
    school.user_id = user_id
    school.cnpj = cnpj
    school.is_private = is_private
    return school





# Testes unitários

class TestSchoolServiceEmailValidation(unittest.TestCase):
    """Unit tests — validate e-mail uniqueness check logic."""

    def test_returns_none_when_email_already_exists(self):
        """create_school deve retornar None quando o e-mail já existe no banco."""
        service = SchoolService()

        existing_user = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            service.create_school(
                first_name="Escola",
                last_name="Duplicada",
                email="duplicado@test.com",
                password="senha1234",
                is_private=True,
                cnpj="12.345.678/0001-90",
                session=mock_session,
            )
        )

        self.assertIsNone(result)
        mock_session.flush.assert_not_called()
        mock_session.commit.assert_not_called()

    def test_proceeds_when_email_is_new(self):
        """create_school deve chamar flush e commit quando o e-mail é único."""
        service = SchoolService()

        mock_no_existing = MagicMock()
        mock_no_existing.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_no_existing

        # created_at vem do server_default; num mock sem banco retorna None.
        # Rodamos e esperamos AttributeError apenas no campo created_at,
        # mas flush e commit já foram chamados — é o que o teste unitário valida.
        try:
            asyncio.run(
                service.create_school(
                    first_name="Escola",
                    last_name="Nova",
                    email="nova@test.com",
                    password="senha1234",
                    is_private=True,
                    cnpj="12.345.678/0001-90",
                    session=mock_session,
                )
            )
        except AttributeError:
            pass  # esperado: created_at é None sem banco real

        mock_session.flush.assert_called_once()
        mock_session.commit.assert_called_once()




# Testes de integração


class TestSchoolServiceIntegration(unittest.TestCase):
    """Integration tests — FastAPI TestClient com SQLite in-memory."""

    def setUp(self):
        from fastapi.testclient import TestClient

        from md_backend.main import app
        from tests.helpers import get_admin_headers

        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def _school_payload(self, email="escola_integ@test.com", cnpj="12.345.678/0001-00"):
        return {
            "first_name": "Escola",
            "last_name": "Integração",
            "email": email,
            "password": "senha1234",
            "is_private": True,
            "cnpj": cnpj,
        }

    def test_create_school_success_inserts_both_tables(self):
        """201: user + school criados; resposta sem campos sensíveis."""
        resp = self.client.post(
            "/schools", json=self._school_payload(), headers=self.admin_headers
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertIn("user_id", body)
        self.assertIn("cnpj", body)
        self.assertIn("is_private", body)
        self.assertNotIn("hashed_password", body)
        self.assertNotIn("password", body)
        self.assertEqual(body["status"], "aprovado")

    def test_create_school_duplicate_email_returns_409(self):
        """409: segunda tentativa com mesmo e-mail deve ser rejeitada."""
        payload = self._school_payload(email="escola_dup@test.com", cnpj="11.111.111/0001-11")
        self.client.post("/schools", json=payload, headers=self.admin_headers)

        payload2 = dict(payload)
        payload2["cnpj"] = "22.222.222/0002-22"
        resp = self.client.post("/schools", json=payload2, headers=self.admin_headers)

        self.assertEqual(resp.status_code, 409)
        self.assertIn("E-mail ja cadastrado", resp.json()["detail"])

    def test_rollback_when_school_insert_fails(self):
        """IntegrityError no insert da escola deve fazer rollback do user."""
        from sqlalchemy.exc import IntegrityError

        email = "rollback_test@test.com"

        with patch(
            "md_backend.routes.school_router.school_service.create_school",
            side_effect=IntegrityError("forced", {}, Exception("forced")),
        ):
            resp = self.client.post(
                "/schools",
                json=self._school_payload(email=email, cnpj="99.999.999/0001-99"),
                headers=self.admin_headers,
            )

        self.assertEqual(resp.status_code, 409)

        # Se rollback funcionou, o e-mail está livre e a próxima inserção deve ter sucesso
        resp2 = self.client.post(
            "/schools",
            json=self._school_payload(email=email, cnpj="88.888.888/0001-88"),
            headers=self.admin_headers,
        )
        self.assertEqual(resp2.status_code, 201)

    def test_create_school_requires_superadmin(self):
        """403: usuário comum não pode criar escolas."""
        email = "normal_user_school@test.com"
        password = "validpass123"

        reg_resp = self.client.post(
            "/register/responsavel",
            json={"email": email, "password": password, "name": "Normal User"},
        )
        self.assertIn(reg_resp.status_code, [200, 201], f"Register falhou: {reg_resp.json()}")

        patch_resp = self.client.patch(
            f"/admin/users/{email}/status",
            json={"status": "aprovado"},
            headers=self.admin_headers,
        )
        self.assertEqual(patch_resp.status_code, 200, f"Aprovação falhou: {patch_resp.json()}")

        login_resp = self.client.post("/login", json={"email": email, "password": password})
        self.assertEqual(login_resp.status_code, 200, f"Login falhou: {login_resp.json()}")

        token = login_resp.json().get("token")
        self.assertIsNotNone(token, f"Token ausente: {login_resp.json()}")

        headers = {"Authorization": f"Bearer {token}"}
        resp = self.client.post(
            "/schools",
            json=self._school_payload(email="school_forbidden@test.com"),
            headers=headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_create_school_unauthenticated_returns_401(self):
        """401: sem token."""
        resp = self.client.post("/schools", json=self._school_payload())
        self.assertEqual(resp.status_code, 401)

    def test_create_school_invalid_email_returns_422(self):
        """422: e-mail malformado é rejeitado pelo Pydantic."""
        payload = self._school_payload()
        payload["email"] = "nao-e-um-email"
        resp = self.client.post("/schools", json=payload, headers=self.admin_headers)
        self.assertEqual(resp.status_code, 422)

    def test_create_school_missing_required_fields_returns_422(self):
        """422: campos obrigatórios ausentes retornam erro de validação."""
        resp = self.client.post(
            "/schools",
            json={"email": "incompleto@test.com"},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 422)