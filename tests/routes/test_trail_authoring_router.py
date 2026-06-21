"""Integration tests for admin trail authoring routes."""

import asyncio
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

import tests.keys_test  # noqa: F401
from md_backend.main import app
from md_backend.utils.database import engine
from md_backend.utils.settings import settings
from tests.helpers import get_admin_headers


class TestTrailAuthoringRouter(unittest.TestCase):
    """Admin authoring endpoints create trail catalog records."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        self._old_google_api_key = settings.GOOGLE_API_KEY
        settings.GOOGLE_API_KEY = ""

    def tearDown(self):
        settings.GOOGLE_API_KEY = self._old_google_api_key
        self.ctx.__exit__(None, None, None)

    def _create_content(self) -> tuple[int, int]:
        subject_resp = self.client.post(
            "/api/admin/subjects",
            json={"name": f"Authoring Route {uuid.uuid4().hex[:8]}", "color": "#000"},
            headers=self.admin_headers,
        )
        self.assertEqual(subject_resp.status_code, 201)
        content_resp = self.client.post(
            "/api/admin/content",
            json={
                "subject_id": subject_resp.json()["id"],
                "title": f"Conteúdo {uuid.uuid4().hex[:8]}",
                "description": "d",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(content_resp.status_code, 201)
        return content_resp.json()["id"], subject_resp.json()["id"]

    def _create_related_content(self, subject_id: int) -> int:
        content_resp = self.client.post(
            "/api/admin/content",
            json={
                "subject_id": subject_id,
                "title": f"Conteúdo relacionado {uuid.uuid4().hex[:8]}",
                "description": "d",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(content_resp.status_code, 201)
        return content_resp.json()["id"]

    def _create_student(self) -> str:
        email = f"authoring_student_{uuid.uuid4().hex[:8]}@example.com"
        response = self.client.post(
            "/api/student",
            json={
                "first_name": "Authoring",
                "last_name": "Student",
                "email": email,
                "password": "securepass123",
                "birth_date": "2010-05-20",
                "student_class": "5th class",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["user_id"]

    def test_create_path_returns_id(self):
        """POST /admin/trails creates a path for existing content."""
        content_id, _subject_id = self._create_content()

        response = self.client.post(
            "/api/admin/trails",
            json={"content_id": content_id, "name": "Álgebra"},
            headers=self.admin_headers,
        )

        self.assertEqual(response.status_code, 201)
        self.assertIn("id", response.json())

    def test_create_path_404_when_content_missing(self):
        """POST /admin/trails returns 404 for missing content."""
        response = self.client.post(
            "/api/admin/trails",
            json={"content_id": 999999},
            headers=self.admin_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_create_manual_trail_generates_quiz_from_existing_content(self):
        """POST /admin/trails/manual creates path, sub-path, generated exercises and items."""
        content_id, _subject_id = self._create_content()

        response = self.client.post(
            "/api/admin/trails/manual",
            json={
                "content_id": content_id,
                "name": "Trilha de Álgebra",
                "description": "Sequência de quizzes sobre equações.",
                "eixo": ["equações do primeiro grau"],
                "question_count": 3,
                "difficulty": 1,
            },
            headers=self.admin_headers,
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertGreater(body["path_id"], 0)
        self.assertGreater(body["sub_path_id"], 0)
        self.assertEqual(len(body["exercise_ids"]), 3)
        self.assertEqual(len(body["item_ids"]), 3)

        async def _count_items():
            async with engine.begin() as conn:
                return (
                    await conn.execute(
                        text(
                            "SELECT COUNT(*) FROM sub_paths_item "
                            "WHERE sub_path_id = :sub_path_id AND type_item = 'EXERCISE'"
                        ),
                        {"sub_path_id": body["sub_path_id"]},
                    )
                ).scalar_one()

        self.assertEqual(asyncio.run(_count_items()), 3)

    def test_create_structured_trail_generates_question_and_resource_sub_steps(self):
        """POST /admin/trails/structured creates grouped sub-steps inside a step."""
        content_id, subject_id = self._create_content()
        related_content_id = self._create_related_content(subject_id)

        response = self.client.post(
            "/api/admin/trails/structured",
            json={
                "title": "Trilha de Álgebra estruturada",
                "description": "Sequência adaptativa completa.",
                "subject_id": subject_id,
                "eixo": ["equações do primeiro grau"],
                "steps": [
                    {
                        "order": 1,
                        "title": "Diagnóstico e revisão",
                        "description": "Avalia e reforça conhecimentos iniciais.",
                        "sub_steps": [
                            {
                                "order": 1,
                                "title": "Quiz diagnóstico",
                                "description": "Avalia conhecimentos iniciais.",
                                "content_id": content_id,
                                "activity": {
                                    "type": "question",
                                    "question_count": 2,
                                    "difficulty": 1,
                                },
                            },
                            {
                                "order": 2,
                                "title": "Revisão guiada",
                                "description": "Texto de apoio relacionado.",
                                "content_id": related_content_id,
                                "activity": {
                                    "type": "text",
                                    "question_count": None,
                                    "difficulty": None,
                                },
                            },
                        ],
                    },
                ],
            },
            headers=self.admin_headers,
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(len(body["sub_path_ids"]), 1)
        self.assertEqual(len(body["exercise_ids"]), 2)
        self.assertEqual(len(body["item_ids"]), 3)

        async def _count_options():
            async with engine.begin() as conn:
                placeholders = ", ".join(
                    f":exercise_id_{index}" for index in range(len(body["exercise_ids"]))
                )
                return (
                    await conn.execute(
                        text(f"SELECT COUNT(*) FROM options WHERE exercise_id IN ({placeholders})"),
                        {
                            f"exercise_id_{index}": exercise_id
                            for index, exercise_id in enumerate(body["exercise_ids"])
                        },
                    )
                ).scalar_one()

        self.assertGreaterEqual(asyncio.run(_count_options()), 8)

        listed = self.client.get(
            "/api/admin/trails",
            params={"query": "Álgebra estruturada"},
            headers=self.admin_headers,
        )
        self.assertEqual(listed.status_code, 200)
        trail = next(item for item in listed.json()["items"] if item["id"] == body["path_id"])
        self.assertEqual(trail["step_count"], 1)
        self.assertEqual(trail["question_count"], 2)
        self.assertEqual(trail["eixo"], ["equações do primeiro grau"])
        self.assertEqual(trail["steps"][0]["title"], "Diagnóstico e revisão")
        self.assertEqual(
            trail["steps"][0]["description"], "Avalia e reforça conhecimentos iniciais."
        )
        self.assertEqual(trail["steps"][0]["activityType"], "question")
        self.assertEqual(trail["steps"][0]["questionCount"], 2)
        self.assertEqual(len(trail["steps"][0]["subSteps"]), 2)
        self.assertEqual(trail["steps"][0]["subSteps"][0]["title"], "Quiz diagnóstico")
        self.assertEqual(trail["steps"][0]["subSteps"][0]["questionCount"], 2)
        self.assertEqual(trail["steps"][0]["subSteps"][1]["activityType"], "text")

    def test_delete_path_with_student_progress_removes_progress_first(self):
        """DELETE /admin/trails/{id} handles progress that points at sub-paths."""
        content_id, _subject_id = self._create_content()
        student_id = self._create_student()
        created = self.client.post(
            "/api/admin/trails/manual",
            json={
                "content_id": content_id,
                "name": "Trilha com progresso",
                "description": "Será removida.",
                "eixo": ["álgebra"],
                "question_count": 1,
                "difficulty": 1,
            },
            headers=self.admin_headers,
        )
        self.assertEqual(created.status_code, 201)
        body = created.json()

        async def _insert_progress():
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO student_path_progress "
                        "(student_id, path_id, current_sub_path, path_status) "
                        "VALUES (:student_id, :path_id, :sub_path_id, 'on_going')"
                    ),
                    {
                        "student_id": student_id,
                        "path_id": body["path_id"],
                        "sub_path_id": body["sub_path_id"],
                    },
                )

        asyncio.run(_insert_progress())

        deleted = self.client.delete(
            f"/api/admin/trails/{body['path_id']}",
            headers=self.admin_headers,
        )

        self.assertEqual(deleted.status_code, 204)

    def test_list_and_update_admin_trails(self):
        """Admin can manage adaptive trails separately from the content list."""
        content_id, _subject_id = self._create_content()
        created = self.client.post(
            "/api/admin/trails/manual",
            json={
                "content_id": content_id,
                "name": "Trilha inicial",
                "description": "Descrição inicial",
                "eixo": ["álgebra"],
                "question_count": 1,
                "difficulty": 1,
            },
            headers=self.admin_headers,
        )
        self.assertEqual(created.status_code, 201)
        path_id = created.json()["path_id"]

        listed = self.client.get("/api/admin/trails", headers=self.admin_headers)
        self.assertEqual(listed.status_code, 200)
        trail = next(item for item in listed.json()["items"] if item["id"] == path_id)
        self.assertEqual(trail["name"], "Trilha inicial")
        self.assertEqual(trail["content_id"], int(content_id))
        self.assertEqual(trail["question_count"], 1)
        self.assertGreaterEqual(listed.json()["total_items"], 1)

        new_content_id, _new_subject_id = self._create_content()
        updated = self.client.patch(
            f"/api/admin/trails/{path_id}",
            json={
                "content_id": new_content_id,
                "name": "Trilha editada",
                "description": "Descrição editada",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name"], "Trilha editada")
        self.assertEqual(updated.json()["description"], "Descrição editada")
        self.assertEqual(updated.json()["content_id"], int(new_content_id))

        filtered = self.client.get(
            "/api/admin/trails",
            params={
                "page": 1,
                "page_size": 5,
                "query": "Trilha editada",
                "subject_id": updated.json()["subject"]["id"],
            },
            headers=self.admin_headers,
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["page"], 1)
        self.assertGreaterEqual(filtered.json()["total_items"], 1)
        self.assertTrue(any(item["id"] == path_id for item in filtered.json()["items"]))

        deleted = self.client.delete(
            f"/api/admin/trails/{path_id}",
            headers=self.admin_headers,
        )
        self.assertEqual(deleted.status_code, 204)

        listed_after_delete = self.client.get("/api/admin/trails", headers=self.admin_headers)
        self.assertEqual(listed_after_delete.status_code, 200)
        self.assertFalse(any(item["id"] == path_id for item in listed_after_delete.json()["items"]))

    def test_authoring_requires_admin(self):
        """Authoring endpoints require superadmin authentication."""
        response = self.client.post("/api/admin/trails", json={"content_id": 1})

        self.assertEqual(response.status_code, 401)
