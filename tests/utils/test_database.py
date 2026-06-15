"""Tests for database utilities."""

import asyncio
import importlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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

    def test_postgres_schema_fix_drops_last_name_not_null(self):
        import md_backend.utils.database as db

        conn = MagicMock()
        conn.dialect.name = "postgresql"
        conn.execute = AsyncMock()

        asyncio.run(db._ensure_user_last_name_nullable(conn))

        conn.execute.assert_awaited_once()
        statement = str(conn.execute.await_args.args[0])
        self.assertIn("ALTER TABLE user_profile", statement)
        self.assertIn("DROP NOT NULL", statement)

    def test_sqlite_schema_fix_is_noop(self):
        import md_backend.utils.database as db

        conn = MagicMock()
        conn.dialect.name = "sqlite"
        conn.execute = AsyncMock()

        asyncio.run(db._ensure_user_last_name_nullable(conn))

        conn.execute.assert_not_awaited()

    def test_item_progress_table_is_created_explicitly(self):
        import md_backend.utils.database as db
        from md_backend.models.db_models import StudentSubPathItemProgress

        conn = MagicMock()
        conn.run_sync = AsyncMock()

        with patch.object(StudentSubPathItemProgress.__table__, "create") as create_mock:
            asyncio.run(db._ensure_item_progress_table(conn))

            conn.run_sync.assert_awaited_once()
            sync_callback = conn.run_sync.await_args.args[0]
            sync_conn = MagicMock()
            sync_callback(sync_conn)

            create_mock.assert_called_once_with(sync_conn, checkfirst=True)

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
