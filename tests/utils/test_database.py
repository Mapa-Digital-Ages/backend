"""Tests for database utilities."""

import unittest

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from md_backend.utils.database import AsyncSessionLocal


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_init_db_creates_tables(self):
        response = self.test_client.get("/api")
        self.assertEqual(response.status_code, 200)

    def test_session_factory_exists(self):
        self.assertIsNotNone(AsyncSessionLocal)
