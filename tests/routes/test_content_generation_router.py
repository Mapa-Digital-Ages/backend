"""Integration tests for admin content generation routes."""

import unittest
import uuid

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from md_backend.utils.settings import settings
from tests.helpers import get_admin_headers


class TestContentGenerationRouter(unittest.TestCase):
    """Admin generation route persists question bank rows."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        self._old_google_api_key = settings.GOOGLE_API_KEY
        settings.GOOGLE_API_KEY = ""

    def tearDown(self):
        settings.GOOGLE_API_KEY = self._old_google_api_key
        self.ctx.__exit__(None, None, None)

    def _create_content(self) -> int:
        subject_resp = self.client.post(
            "/api/admin/subjects",
            json={"name": f"Generation Route {uuid.uuid4().hex[:8]}", "color": "#000"},
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
        return content_resp.json()["id"]

    def test_generate_questions_creates_exercises(self):
        """POST /admin/contents/{id}/generate-questions creates exercises."""
        content_id = self._create_content()

        response = self.client.post(
            f"/api/admin/contents/{content_id}/generate-questions",
            json={"count": 2, "difficulty": 1, "eixo": ["frações"]},
            headers=self.admin_headers,
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(len(body["created_exercise_ids"]), 2)
        self.assertEqual(len(body["questions"]), 2)

    def test_generate_404_when_content_missing(self):
        """Generation returns 404 when content does not exist."""
        response = self.client.post(
            "/api/admin/contents/999999/generate-questions",
            json={"eixo": ["frações"]},
            headers=self.admin_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_generation_requires_admin(self):
        """Generation endpoints require superadmin authentication."""
        response = self.client.post(
            "/api/admin/contents/1/generate-questions",
            json={"eixo": ["frações"]},
        )

        self.assertEqual(response.status_code, 401)
