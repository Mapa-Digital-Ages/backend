"""Integration tests for admin trail authoring routes."""

import unittest
import uuid

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from tests.helpers import get_admin_headers


class TestTrailAuthoringRouter(unittest.TestCase):
    """Admin authoring endpoints create trail catalog records."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def _create_content(self) -> int:
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
        return content_resp.json()["id"]

    def test_create_path_returns_id(self):
        """POST /admin/trails creates a path for existing content."""
        content_id = self._create_content()

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

    def test_authoring_requires_admin(self):
        """Authoring endpoints require superadmin authentication."""
        response = self.client.post("/api/admin/trails", json={"content_id": 1})

        self.assertEqual(response.status_code, 401)
