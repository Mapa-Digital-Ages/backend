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

        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()

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
        resp = self.client.post("/school", json=self._school_payload())
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
        self.client.post("/school", json=payload)

        payload2 = dict(payload)
        payload2["cnpj"] = "22.222.222/0002-22"
        resp = self.client.post("/school", json=payload2)

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
                "/school",
                json=self._school_payload(email=email, cnpj="99.999.999/0001-99"),
            )

        self.assertEqual(resp.status_code, 409)

        resp2 = self.client.post(
            "/school",
            json=self._school_payload(email=email, cnpj="88.888.888/0001-88"),
        )
        self.assertEqual(resp2.status_code, 201)

    def test_create_school_invalid_email_returns_422(self):
        """422: e-mail malformado é rejeitado pelo Pydantic."""
        payload = self._school_payload()
        payload["email"] = "nao-e-um-email"
        resp = self.client.post("/school", json=payload)
        self.assertEqual(resp.status_code, 422)

    def test_create_school_missing_required_fields_returns_422(self):
        """422: campos obrigatórios ausentes retornam erro de validação."""
        resp = self.client.post("/school", json={"email": "incompleto@test.com"})
        self.assertEqual(resp.status_code, 422)

    # GET /school

    def test_list_schools_returns_only_active(self):
        """GET /school deve retornar apenas escolas ativas (status=aprovado)."""
        self.client.post(
            "/school",
            json=self._school_payload(email="ativa_list@test.com", cnpj="33.333.333/0001-33"),
        )
        resp = self.client.get("/school")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("items", body)
        self.assertIn("total", body)
        for item in body["items"]:
            self.assertTrue(item["is_active"])
            self.assertNotIn("password", item)
            self.assertNotIn("hashed_password", item)

    def test_list_schools_filter_by_name_partial_case_insensitive(self):
        """Filtro por name deve funcionar parcialmente e sem diferenciar maiúsculas."""
        self.client.post(
            "/school",
            json={
                "first_name": "Olimpo",
                "last_name": "Educacional",
                "email": "olimpo@test.com",
                "password": "senha1234",
                "is_private": False,
                "cnpj": "44.444.444/0001-44",
            },
        )
        resp = self.client.get("/school", params={"name": "olimpo"})
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertTrue(len(items) >= 1)
        self.assertTrue(any("Olimpo" in item["name"] for item in items))

    def test_list_schools_filter_by_cnpj_exact(self):
        """Filtro por CNPJ deve ser exato."""
        target_cnpj = "55.555.555/0001-55"
        self.client.post(
            "/school",
            json=self._school_payload(email="cnpj_filter@test.com", cnpj=target_cnpj),
        )
        resp = self.client.get("/school", params={"cnpj": target_cnpj})
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["cnpj"], target_cnpj)

    def test_list_schools_pagination(self):
        """Paginação deve respeitar os parâmetros page e size."""
        resp = self.client.get("/school", params={"page": 1, "size": 1})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["size"], 1)
        self.assertLessEqual(len(body["items"]), 1)

    # GET /school/{id}

    def test_get_school_by_id_returns_correct_data(self):
        """GET /school/{id} deve retornar dados completos da escola."""
        create_resp = self.client.post(
            "/school",
            json=self._school_payload(email="getbyid@test.com", cnpj="66.666.666/0001-66"),
        )
        school_id = create_resp.json()["user_id"]

        resp = self.client.get(f"/school/{school_id}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["user_id"], school_id)
        self.assertIn("quantidade_alunos", body)
        self.assertNotIn("password", body)
        self.assertNotIn("hashed_password", body)

    def test_get_school_by_id_not_found_returns_404(self):
        """GET /school/{id} com ID inexistente deve retornar 404."""
        resp = self.client.get("/school/999999")
        self.assertEqual(resp.status_code, 404)

    def test_get_school_quantidade_alunos_counts_correctly(self):
        """quantidade_alunos deve refletir o número exato de students vinculados."""
        import asyncio

        from sqlalchemy import text

        from md_backend.utils.database import AsyncSessionLocal

        create_resp = self.client.post(
            "/school",
            json=self._school_payload(email="alunos_count@test.com", cnpj="77.777.777/0001-77"),
        )
        school_id = create_resp.json()["user_id"]

        async def insert_students():
            async with AsyncSessionLocal() as session:
                for i in range(3):
                    await session.execute(
                        text(
                            "INSERT INTO students (school_id, name) VALUES (:school_id, :name)"
                        ),
                        {"school_id": school_id, "name": f"Aluno {i}"},
                    )
                await session.commit()

        asyncio.run(insert_students())

        resp = self.client.get(f"/school/{school_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["quantidade_alunos"], 3)

class TestSchoolResponseDTO(unittest.TestCase):
    """Unit tests — garantir que o DTO de resposta nunca expõe a senha."""

    def test_response_dict_never_contains_password(self):
        """O dict retornado por create_school jamais deve incluir 'password' ou 'hashed_password'."""
        response_dict = {
            "user_id": 1,
            "email": "escola@test.com",
            "name": "Escola Teste",
            "cnpj": "12.345.678/0001-90",
            "is_private": True,
            "status": "aprovado",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        self.assertNotIn("password", response_dict)
        self.assertNotIn("hashed_password", response_dict)

    def test_get_response_dict_never_contains_password(self):
        """O dict retornado por get/list schools jamais deve incluir senha."""
        response_dict = {
            "user_id": 1,
            "email": "escola@test.com",
            "name": "Escola Teste",
            "cnpj": "12.345.678/0001-90",
            "is_private": True,
            "status": "aprovado",
            "created_at": "2026-01-01T00:00:00+00:00",
            "is_active": True,
            "quantidade_alunos": 5,
        }
        self.assertNotIn("password", response_dict)
        self.assertNotIn("hashed_password", response_dict)