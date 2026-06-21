"""Tests for the school CSV batch-import pipeline (POST /api/school/batch).

Covers both the HTTP-level All-or-Nothing contract (via TestClient) and the
dual bulk-insert mechanics of SchoolService.import_school_batch with a
mocked AsyncSession.
"""

import asyncio
import io
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import tests.keys_test  # noqa: F401
from md_backend.services.csv_processor_service import CSVHeaderError
from md_backend.services.school_service import SchoolService

VALID_HEADER = "first_name,last_name,email,phone_number,is_private\r\n"


def _csv_file(content: str, filename: str = "schools.csv"):
    """Build a multipart file tuple from a CSV string body."""
    return {"file": (filename, io.BytesIO(content.encode("utf-8")), "text/csv")}


class TestSchoolBatchImportIntegration(unittest.TestCase):
    """Integration tests against /api/school/batch via FastAPI TestClient."""

    def setUp(self):
        from fastapi.testclient import TestClient

        from md_backend.main import app
        from tests.helpers import get_admin_headers

        self.ctx = TestClient(app, raise_server_exceptions=True)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_batch_import_success_returns_201(self):
        unique = uuid.uuid4().hex[:8]
        csv_body = VALID_HEADER + (
            f"Ana,Silva,ana.{unique}@test.com,11999990000,true\r\n"
            f"Bruno,Souza,bruno.{unique}@test.com,,false\r\n"
        )
        resp = self.client.post(
            "/api/school/batch",
            files=_csv_file(csv_body),
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["total_processed"], 2)
        self.assertEqual(body["created"], 2)
        self.assertEqual(body["failed"], 0)

    def test_batch_import_creates_login_capable_school_accounts(self):
        unique = uuid.uuid4().hex[:8]
        email = f"created.{unique}@test.com"
        csv_body = VALID_HEADER + f"Carla,Lima,{email},,true\r\n"

        resp = self.client.post(
            "/api/school/batch",
            files=_csv_file(csv_body),
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 201)

        list_resp = self.client.get(
            "/api/school", params={"name": "Carla"}, headers=self.admin_headers
        )
        emails = [item["email"] for item in list_resp.json()["items"]]
        self.assertIn(email, emails)

    def test_batch_import_duplicate_email_returns_aborted_structure(self):
        existing_email = f"dup.{uuid.uuid4().hex[:8]}@test.com"
        self.client.post(
            "/api/school",
            json={
                "first_name": "Existing",
                "last_name": "School",
                "email": existing_email,
                "password": "password1234",
                "is_private": True,
            },
            headers=self.admin_headers,
        )

        fresh_email = f"fresh.{uuid.uuid4().hex[:8]}@test.com"
        csv_body = VALID_HEADER + (
            f"Fresh,School,{fresh_email},,true\r\nDup,School,{existing_email},,false\r\n"
        )

        resp = self.client.post(
            "/api/school/batch",
            files=_csv_file(csv_body),
            headers=self.admin_headers,
        )

        # Com partial success: Fresh é salva, Dup falha → 201 partial
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["status"], "partial")
        self.assertEqual(body["total_processed"], 2)
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["failed"], 1)
        self.assertEqual(len(body["errors"]), 1)
        self.assertEqual(body["errors"][0]["email"], existing_email)
        self.assertIn("cadastrado", body["errors"][0]["reason"])

        # Fresh foi salva normalmente
        list_resp = self.client.get(
            "/api/school", params={"name": "Fresh"}, headers=self.admin_headers
        )
        self.assertEqual(list_resp.json()["total"], 1)

    def test_batch_import_invalid_email_returns_aborted_with_row_number(self):
        csv_body = VALID_HEADER + "Ana,Silva,invalido.com,11999990000,true\r\n"

        resp = self.client.post(
            "/api/school/batch",
            files=_csv_file(csv_body),
            headers=self.admin_headers,
        )

        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertEqual(body["status"], "aborted")
        self.assertEqual(body["created"], 0)
        self.assertEqual(body["failed"], 1)
        self.assertEqual(body["errors"][0]["row"], 2)

    def test_batch_import_missing_column_returns_400(self):
        csv_body = "first_name,last_name,email,is_private\r\nAna,Silva,ana@test.com,true\r\n"

        resp = self.client.post(
            "/api/school/batch",
            files=_csv_file(csv_body),
            headers=self.admin_headers,
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("detail", resp.json())

    def test_batch_import_extra_column_returns_400(self):
        csv_body = (
            "first_name,last_name,email,phone_number,is_private,extra\r\n"
            "Ana,Silva,ana@test.com,,true,oops\r\n"
        )

        resp = self.client.post(
            "/api/school/batch",
            files=_csv_file(csv_body),
            headers=self.admin_headers,
        )

        self.assertEqual(resp.status_code, 400)

    def test_batch_import_unauthenticated_returns_401(self):
        resp = self.client.post(
            "/api/school/batch",
            files=_csv_file(VALID_HEADER + "Ana,Silva,ana@test.com,,true\r\n"),
        )
        self.assertEqual(resp.status_code, 401)

    def test_batch_import_non_superadmin_returns_403(self):
        from tests.helpers import create_approved_user

        email = f"notadmin.{uuid.uuid4().hex[:8]}@test.com"
        token = create_approved_user(self.client, self.admin_headers, email)

        resp = self.client.post(
            "/api/school/batch",
            files=_csv_file(VALID_HEADER + "Ana,Silva,ana2@test.com,,true\r\n"),
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_batch_import_mixed_valid_and_invalid_rows_creates_nothing(self):
        unique = uuid.uuid4().hex[:8]
        csv_body = VALID_HEADER + (
            f"Ana,Silva,ana.{unique}@test.com,,true\r\nBruno,Souza,invalido.com,,false\r\n"
        )

        resp = self.client.post(
            "/api/school/batch",
            files=_csv_file(csv_body),
            headers=self.admin_headers,
        )

        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["status"], "partial")
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["failed"], 1)

        # A linha válida (Ana) foi salva normalmente
        list_resp = self.client.get(
            "/api/school", params={"name": "Ana"}, headers=self.admin_headers
        )
        self.assertEqual(list_resp.json()["total"], 1)

        # A linha inválida (Bruno) não foi salva
        list_resp = self.client.get(
            "/api/school", params={"name": "Bruno"}, headers=self.admin_headers
        )
        self.assertEqual(list_resp.json()["total"], 0)

    def test_batch_import_all_rows_invalid_returns_400(self):
        csv_body = VALID_HEADER + (
            "Ana,Silva,invalido1.com,,true\r\nBruno,Souza,invalido2.com,,false\r\n"
        )

        resp = self.client.post(
            "/api/school/batch",
            files=_csv_file(csv_body),
            headers=self.admin_headers,
        )

        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertEqual(body["status"], "aborted")
        self.assertEqual(body["created"], 0)
        self.assertEqual(body["failed"], 2)


class TestSchoolBatchImportDualInsertUnit(unittest.TestCase):
    """Unit tests mocking the AsyncSession to verify the dual bulk-insert mechanics."""

    def _csv_bytes(self, n: int = 2) -> bytes:
        rows = "".join(f"User{i},Last{i},user{i}@test.com,,true\r\n" for i in range(n))
        return (VALID_HEADER + rows).encode("utf-8")

    def test_execute_called_exactly_twice_with_insert_and_returning(self):
        service = SchoolService()

        mock_session = AsyncMock()

        # First execute(): duplicate-email integrity check -> no matches.
        integrity_result = MagicMock()
        integrity_result.scalars.return_value.all.return_value = []

        # Second execute(): bulk insert into UserProfile, returning fresh UUIDs.
        user_a_id, user_b_id = uuid.uuid4(), uuid.uuid4()
        returning_result = MagicMock()
        returning_result.all.return_value = [
            (user_a_id, "user0@test.com"),
            (user_b_id, "user1@test.com"),
        ]

        # Third execute(): bulk insert into SchoolProfile.
        school_insert_result = MagicMock()

        mock_session.execute.side_effect = [
            integrity_result,
            returning_result,
            school_insert_result,
        ]

        result = asyncio.run(
            service.import_school_batch(
                raw_content=self._csv_bytes(2),
                session=mock_session,
                background_tasks=None,
            )
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["created"], 2)
        self.assertEqual(mock_session.execute.call_count, 3)

        # Second and third calls must be INSERT statements; the second must carry RETURNING.
        insert_calls = mock_session.execute.call_args_list[1:]
        for executed_call in insert_calls:
            stmt = executed_call.args[0]
            self.assertEqual(stmt.__class__.__name__.lower().startswith("insert"), True)

        users_stmt = insert_calls[0].args[0]
        self.assertTrue(users_stmt._returning)

        mock_session.commit.assert_called_once()

    def test_aborted_batch_never_calls_insert(self):
        service = SchoolService()
        mock_session = AsyncMock()

        # Chamada 1: SELECT de integridade → user0 já existe
        integrity_result = MagicMock()
        integrity_result.scalars.return_value.all.return_value = ["user0@test.com"]

        # Chamada 2: INSERT UserProfile → retorna tuplas (uuid, email)
        user_id = uuid.uuid4()
        insert_users_result = MagicMock()
        insert_users_result.all.return_value = [(user_id, "user1@test.com")]

        # Chamada 3: INSERT SchoolProfile
        insert_schools_result = MagicMock()

        mock_session.execute.side_effect = [
            integrity_result,
            insert_users_result,
            insert_schools_result,
        ]

        result = asyncio.run(
            service.import_school_batch(
                raw_content=self._csv_bytes(2),
                session=mock_session,
                background_tasks=None,
            )
        )

        # user0 falha (duplicado), user1 é salvo → partial
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["failed"], 1)
        # Os dois inserts devem ter ocorrido (só user1 foi inserido)
        self.assertEqual(mock_session.execute.call_count, 3)
        mock_session.commit.assert_called_once()

    def test_schema_errors_skip_integrity_query_entirely(self):
        service = SchoolService()
        mock_session = AsyncMock()

        bad_csv = (VALID_HEADER + "Ana,Silva,invalido.com,,true\r\n").encode("utf-8")

        result = asyncio.run(
            service.import_school_batch(
                raw_content=bad_csv,
                session=mock_session,
                background_tasks=None,
            )
        )

        self.assertEqual(result["status"], "aborted")
        # No valid rows at all -> the duplicate-email check is skipped (no DB hit).
        mock_session.execute.assert_not_called()
        mock_session.commit.assert_not_called()

    def test_header_mismatch_raises_csv_header_error_without_touching_db(self):
        service = SchoolService()
        mock_session = AsyncMock()

        bad_csv = b"first_name,last_name,email,is_private\r\nAna,Silva,ana@test.com,true\r\n"

        with self.assertRaises(CSVHeaderError):
            asyncio.run(service.import_school_batch(raw_content=bad_csv, session=mock_session))

        mock_session.execute.assert_not_called()

    def test_background_tasks_receive_one_reset_email_per_created_user(self):
        password_reset_service = AsyncMock()
        password_reset_service.prepare_initial_password_setup.return_value = "123456"
        service = SchoolService(password_reset_service=password_reset_service)
        mock_session = AsyncMock()
        mock_background_tasks = MagicMock()

        integrity_result = MagicMock()
        integrity_result.scalars.return_value.all.return_value = []

        user_id = uuid.uuid4()
        returning_result = MagicMock()
        returning_result.all.return_value = [(user_id, "user0@test.com")]

        mock_session.execute.side_effect = [integrity_result, returning_result, MagicMock()]

        with patch(
            "md_backend.services.school_service.hash_password",
            new_callable=AsyncMock,
            return_value="hashed-password",
        ):
            asyncio.run(
                service.import_school_batch(
                    raw_content=self._csv_bytes(1),
                    session=mock_session,
                    background_tasks=mock_background_tasks,
                )
            )

        password_reset_service.dispatch_initial_password_setup_email.assert_awaited_once_with(
            email="user0@test.com",
            code="123456",
            background_tasks=mock_background_tasks,
        )

    def test_inline_email_dispatch_when_no_background_tasks_provided(self):
        password_reset_service = AsyncMock()
        password_reset_service.prepare_initial_password_setup.return_value = "654321"
        service = SchoolService(password_reset_service=password_reset_service)
        mock_session = AsyncMock()

        integrity_result = MagicMock()
        integrity_result.scalars.return_value.all.return_value = []

        user_id = uuid.uuid4()
        returning_result = MagicMock()
        returning_result.all.return_value = [(user_id, "user0@test.com")]

        mock_session.execute.side_effect = [integrity_result, returning_result, MagicMock()]

        with patch(
            "md_backend.services.school_service.hash_password",
            new_callable=AsyncMock,
            return_value="hashed-password",
        ):
            asyncio.run(
                service.import_school_batch(
                    raw_content=self._csv_bytes(1),
                    session=mock_session,
                    background_tasks=None,
                )
            )

        password_reset_service.dispatch_initial_password_setup_email.assert_awaited_once_with(
            email="user0@test.com",
            code="654321",
            background_tasks=None,
        )


if __name__ == "__main__":
    unittest.main()
