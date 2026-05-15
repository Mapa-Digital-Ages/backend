"""Tests for database utilities."""

import importlib
import unittest
from unittest.mock import MagicMock, patch

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


class TestDatabasePostgresEngineConfig(unittest.TestCase):
    """Cover the non-sqlite branch in database module init."""

    def test_postgres_url_sets_pool_kwargs(self):
        import md_backend.utils.database as db
        from md_backend.utils.settings import settings

        with (
            patch.object(settings, "DATABASE_URL", "postgresql+asyncpg://u:p@host/db"),
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=MagicMock(),
            ) as create_engine_mock,
            patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=MagicMock()),
        ):
            try:
                importlib.reload(db)
                create_engine_mock.assert_called_once()
                kwargs = create_engine_mock.call_args.kwargs
                self.assertTrue(kwargs["pool_pre_ping"])
                self.assertEqual(kwargs["pool_recycle"], 1800)
                self.assertEqual(kwargs["pool_size"], 10)
                self.assertEqual(kwargs["max_overflow"], 20)
                self.assertNotIn("connect_args", kwargs)
                self.assertNotIn("poolclass", kwargs)
            finally:
                # Restore the real sqlite engine for subsequent tests.
                importlib.reload(db)
