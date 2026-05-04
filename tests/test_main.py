"""Tests for the main app entry point."""

import unittest

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app


class TestMain(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app)
        self.test_client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_root_endpoint(self):
        response = self.test_client.get("/api")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({"detail": "Alive!"}, response.json())
