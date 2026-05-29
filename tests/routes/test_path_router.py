"""Integration tests for trail (path) endpoints."""

import asyncio
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

import tests.keys_test  # noqa: F401
from md_backend.main import app
from md_backend.utils.database import engine
from tests.helpers import get_admin_headers


def _create_student(client, admin_headers):
    """Create a student and return (student_id, auth_headers)."""
    email = f"trail_student_{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "first_name": "Trail",
        "last_name": "Student",
        "email": email,
        "password": "securepass123",
        "birth_date": "2010-05-20",
        "student_class": "5th class",
    }
    resp = client.post("/api/student", json=payload, headers=admin_headers)
    student_id = resp.json()["user_id"]
    token_resp = client.post("/api/login", json={"email": email, "password": "securepass123"})
    token = token_resp.json()["token"]
    return student_id, {"Authorization": f"Bearer {token}"}


def _seed_trail(student_id: str) -> int:
    """Insert Path + Content + Subject + StudentPathProgress via SQL. Returns path_id."""

    async def _insert():
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO subjects (name, slug, color) VALUES (:n, :s, :c) "
                    "ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name"
                ),
                {"n": "Matemática Trail Test", "s": "matematica-trail-test", "c": "#FF0000"},
            )
            subject_row = await conn.execute(
                text("SELECT id FROM subjects WHERE slug = 'matematica-trail-test'")
            )
            subject_id = subject_row.scalar_one()

            content_name = f"Álgebra Trail Test {uuid.uuid4().hex[:6]}"
            await conn.execute(
                text(
                    "INSERT INTO contents (subject_id, name, description) "
                    "VALUES (:sid, :n, :d)"
                ),
                {"sid": subject_id, "n": content_name, "d": "desc"},
            )
            content_row = await conn.execute(
                text("SELECT id FROM contents WHERE name = :n"), {"n": content_name}
            )
            content_id = content_row.scalar_one()

            path_name = f"Trilha de Álgebra {uuid.uuid4().hex[:6]}"
            await conn.execute(
                text(
                    "INSERT INTO paths (contents_id, name, description) "
                    "VALUES (:cid, :n, :d)"
                ),
                {"cid": content_id, "n": path_name, "d": "trilha desc"},
            )
            path_row = await conn.execute(
                text("SELECT id FROM paths WHERE name = :n"), {"n": path_name}
            )
            path_id = path_row.scalar_one()

            await conn.execute(
                text("INSERT INTO sub_paths (path_id) VALUES (:pid)"),
                {"pid": path_id},
            )
            sub_path_row = await conn.execute(
                text("SELECT id FROM sub_paths WHERE path_id = :pid ORDER BY id LIMIT 1"),
                {"pid": path_id},
            )
            sub_path_id = sub_path_row.scalar_one()

            await conn.execute(
                text(
                    "INSERT INTO student_path_progress "
                    "(student_id, path_id, current_sub_path, path_status) "
                    "VALUES (:sid, :pid, :spid, 'on_going') "
                    "ON CONFLICT DO NOTHING"
                ),
                {"sid": student_id, "pid": path_id, "spid": sub_path_id},
            )

            return path_id

    return asyncio.run(_insert())


class TestPathRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        self.student_id, self.student_headers = _create_student(
            self.client, self.admin_headers
        )
        self.path_id = _seed_trail(self.student_id)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_list_trails_returns_200_for_own_student(self):
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertTrue(any(t["id"] == str(self.path_id) for t in data))

    def test_list_trails_returns_403_for_other_student(self):
        other_id, _ = _create_student(self.client, self.admin_headers)
        resp = self.client.get(
            f"/api/student/{other_id}/trails",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 403)

    def test_get_trail_detail_returns_200(self):
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails/{self.path_id}",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], str(self.path_id))
        self.assertIn("steps", data)
        self.assertIn("subject", data)

    def test_get_trail_detail_returns_404_for_unknown_path(self):
        resp = self.client.get(
            f"/api/student/{self.student_id}/trails/999999",
            headers=self.student_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_list_trails_returns_401_without_auth(self):
        resp = self.client.get(f"/api/student/{self.student_id}/trails")
        self.assertEqual(resp.status_code, 401)
