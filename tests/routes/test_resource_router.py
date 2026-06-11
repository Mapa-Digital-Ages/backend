"""Integration tests for resource endpoints (student + admin)."""

import unittest
import uuid

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from tests.helpers import get_admin_headers


# Helpers
def _make_subject(client, admin_headers, name=None):
    name = name or f"Subject {uuid.uuid4()}"
    resp = client.post(
        "/api/admin/subjects",
        json={"name": name, "slug": name.lower().replace(" ", "-"), "color": "#fff"},
        headers=admin_headers,
    )
    return resp.json()["id"]


def _make_content(client, admin_headers, subject_id):
    resp = client.post(
        "/api/admin/content",
        json={"subject_id": subject_id, "title": f"Content {uuid.uuid4()}", "description": ""},
        headers=admin_headers,
    )
    return resp.json()["id"]


def _make_resource(client, admin_headers, content_id, title="Test Resource", rtype="link"):
    """Create a resource via the admin API endpoint."""
    resp = client.post(
        "/api/admin/resources",
        json={
            "content_id": content_id,
            "type": rtype,
            "title": title,
            "file_url": "https://example.com/resource",
        },
        headers=admin_headers,
    )
    if resp.status_code != 201:
        raise RuntimeError(f"Failed to create resource: {resp.status_code} - {resp.text}")
    return resp.json()["id"]


# 401 — student endpoints without token
class TestListResourcesUnauthorized(unittest.TestCase):
    """GET /contents/{id}/resources must block requests without a token."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_missing_token_returns_401(self):
        response = self.client.get("/api/contents/1/resources")
        self.assertEqual(response.status_code, 401)

    def test_invalid_token_returns_401(self):
        response = self.client.get(
            "/api/contents/1/resources",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        self.assertEqual(response.status_code, 401)


class TestDownloadUrlUnauthorized(unittest.TestCase):
    """GET /resources/{id}/download-url must block requests without a token."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_missing_token_returns_401(self):
        response = self.client.get("/api/resources/1/download-url")
        self.assertEqual(response.status_code, 401)

    def test_invalid_token_returns_401(self):
        response = self.client.get(
            "/api/resources/1/download-url",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        self.assertEqual(response.status_code, 401)


# Student happy-path
class TestListResourcesAuthenticated(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        subject_id = _make_subject(self.client, self.admin_headers)
        self.content_id = _make_content(self.client, self.admin_headers, subject_id)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_returns_200_with_empty_list(self):
        resp = self.client.get(
            f"/api/contents/{self.content_id}/resources",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_nonexistent_content_returns_empty_list(self):
        resp = self.client.get(
            "/api/contents/999999/resources",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])


class TestDownloadUrlAuthenticated(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_nonexistent_resource_returns_404(self):
        resp = self.client.get(
            "/api/resources/999999/download-url",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)


# Admin — list resources
class TestAdminListResources(unittest.TestCase):
    """GET /admin/resources."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        subject_id = _make_subject(self.client, self.admin_headers)
        self.content_id = _make_content(self.client, self.admin_headers, subject_id)
        self.resource_id = _make_resource(self.client, self.admin_headers, self.content_id)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_returns_200_paginated(self):
        resp = self.client.get("/api/admin/resources", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)
        self.assertIn("total_items", data)
        self.assertIn("page", data)
        self.assertIn("total_pages", data)

    def test_filter_by_content_id(self):
        resp = self.client.get(
            "/api/admin/resources",
            params={"content_id": self.content_id},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertTrue(all(i["content_id"] == self.content_id for i in items))

    def test_filter_by_query(self):
        resp = self.client.get(
            "/api/admin/resources",
            params={"query": "Test Resource"},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertTrue(any(i["id"] == self.resource_id for i in items))

    def test_no_token_returns_401(self):
        resp = self.client.get("/api/admin/resources")
        self.assertEqual(resp.status_code, 401)


# Admin — get resource by ID
class TestAdminGetResource(unittest.TestCase):
    """GET /admin/resources/{id}."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        subject_id = _make_subject(self.client, self.admin_headers)
        content_id = _make_content(self.client, self.admin_headers, subject_id)
        self.resource_id = _make_resource(self.client, self.admin_headers, content_id)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_returns_full_detail(self):
        resp = self.client.get(
            f"/api/admin/resources/{self.resource_id}",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for field in (
            "id",
            "content_id",
            "type",
            "title",
            "file_url",
            "storage_key",
            "file_name",
            "file_type",
            "file_size_bytes",
            "created_at",
            "updated_at",
        ):
            self.assertIn(field, data)

    def test_nonexistent_returns_404(self):
        resp = self.client.get("/api/admin/resources/999999", headers=self.admin_headers)
        self.assertEqual(resp.status_code, 404)


# Admin — PATCH resource (core requirement)
class TestAdminPatchResource(unittest.TestCase):
    """PATCH /admin/resources/{id} — metadata update without touching storage fields."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        subject_id = _make_subject(self.client, self.admin_headers)
        content_id = _make_content(self.client, self.admin_headers, subject_id)
        self.resource_id = _make_resource(
            self.client, self.admin_headers, content_id, title="Original Title"
        )

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_updates_title_successfully(self):
        resp = self.client.patch(
            f"/api/admin/resources/{self.resource_id}",
            json={"title": "Updated Title"},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["title"], "Updated Title")

    def test_storage_key_and_file_url_unchanged_after_patch(self):
        """Core requirement: PATCH must never modify storage fields."""
        # Fetch original values
        original = self.client.get(
            f"/api/admin/resources/{self.resource_id}",
            headers=self.admin_headers,
        ).json()

        # Apply a title update
        self.client.patch(
            f"/api/admin/resources/{self.resource_id}",
            json={"title": "Another Title"},
            headers=self.admin_headers,
        )

        # Re-fetch and compare storage fields
        updated = self.client.get(
            f"/api/admin/resources/{self.resource_id}",
            headers=self.admin_headers,
        ).json()

        self.assertEqual(updated["storage_key"], original["storage_key"])
        self.assertEqual(updated["file_url"], original["file_url"])
        self.assertEqual(updated["file_name"], original["file_name"])
        self.assertEqual(updated["file_type"], original["file_type"])
        self.assertEqual(updated["file_size_bytes"], original["file_size_bytes"])

    def test_nonexistent_resource_returns_404(self):
        resp = self.client.patch(
            "/api/admin/resources/999999",
            json={"title": "x"},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_no_token_returns_401(self):
        resp = self.client.patch(
            f"/api/admin/resources/{self.resource_id}",
            json={"title": "x"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_empty_patch_body_keeps_existing_title(self):
        """Sending an empty body must be a no-op."""
        original = self.client.get(
            f"/api/admin/resources/{self.resource_id}",
            headers=self.admin_headers,
        ).json()["title"]

        resp = self.client.patch(
            f"/api/admin/resources/{self.resource_id}",
            json={},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["title"], original)


# Admin — DELETE resource
class TestAdminDeleteResource(unittest.TestCase):
    """DELETE /admin/resources/{id}."""

    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)
        subject_id = _make_subject(self.client, self.admin_headers)
        self.content_id = _make_content(self.client, self.admin_headers, subject_id)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_delete_existing_resource_returns_200(self):
        resource_id = _make_resource(
            self.client, self.admin_headers, self.content_id, title="To Be Deleted"
        )
        resp = self.client.delete(
            f"/api/admin/resources/{resource_id}",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("deleted", resp.json()["detail"].lower())

    def test_deleted_resource_no_longer_retrievable(self):
        """After DELETE, GET on the same ID must return 404."""
        resource_id = _make_resource(
            self.client, self.admin_headers, self.content_id, title="Gone Resource"
        )
        self.client.delete(
            f"/api/admin/resources/{resource_id}",
            headers=self.admin_headers,
        )
        resp = self.client.get(
            f"/api/admin/resources/{resource_id}",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_delete_nonexistent_resource_returns_404(self):
        resp = self.client.delete(
            "/api/admin/resources/999999",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_no_token_returns_401(self):
        resource_id = _make_resource(
            self.client, self.admin_headers, self.content_id, title="Auth Test"
        )
        resp = self.client.delete(f"/api/admin/resources/{resource_id}")
        self.assertEqual(resp.status_code, 401)

    def test_double_delete_returns_404(self):
        """Deleting an already-deleted resource must return 404, not 500."""
        resource_id = _make_resource(
            self.client, self.admin_headers, self.content_id, title="Double Delete"
        )
        self.client.delete(
            f"/api/admin/resources/{resource_id}",
            headers=self.admin_headers,
        )
        resp = self.client.delete(
            f"/api/admin/resources/{resource_id}",
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 404)
