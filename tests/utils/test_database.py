"""Tests for database utilities."""

import asyncio
import importlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app
from md_backend.utils.database import AsyncSessionLocal


class Savepoint:
    async def __aenter__(self):
        """Enter the fake savepoint."""
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        """Exit the fake savepoint without suppressing exceptions."""
        return False


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
        conn.begin_nested.return_value = Savepoint()

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

    def test_sponsorship_migration_preserves_current_model_columns_after_optional_failure(self):
        import md_backend.utils.database as db

        class Conn:
            def __init__(self):
                self.dialect = MagicMock()
                self.dialect.name = "postgresql"
                self.executed: list[str] = []
                self.savepoints = 0

            def begin_nested(self):
                self.savepoints += 1
                return Savepoint()

            async def execute(self, statement):
                sql = str(statement)
                self.executed.append(sql)
                if "ADD COLUMN IF NOT EXISTS request_id" in sql:
                    raise RuntimeError("already migrated")

        conn = Conn()

        asyncio.run(db._migrate_sponsorship_tables(conn))

        sql = "\n".join(conn.executed)
        self.assertNotIn("DROP COLUMN IF EXISTS requested_spots", sql)
        self.assertNotIn("DROP COLUMN IF EXISTS available_spots", sql)
        self.assertNotIn("DROP CONSTRAINT school_company_partnership_pkey", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS requested_spots", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS available_spots", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS id UUID", sql)
        self.assertIn("SET id = gen_random_uuid() WHERE id IS NULL", sql)
        self.assertIn("school_company_partnership_id_key UNIQUE (id)", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS granted_spots", sql)
        self.assertGreaterEqual(conn.savepoints, 1)

    def test_resource_migration_continues_after_optional_failure(self):
        import md_backend.utils.database as db

        class Conn:
            def __init__(self):
                self.dialect = MagicMock()
                self.dialect.name = "postgresql"
                self.executed: list[str] = []
                self.savepoints = 0

            def begin_nested(self):
                self.savepoints += 1
                return Savepoint()

            async def execute(self, statement):
                sql = str(statement)
                self.executed.append(sql)
                if "ALTER COLUMN type TYPE resource_type_enum" in sql:
                    raise RuntimeError("legacy enum mismatch")

        conn = Conn()

        asyncio.run(db._migrate_resources_table(conn))

        sql = "\n".join(conn.executed)
        self.assertIn("ALTER COLUMN type TYPE resource_type_enum", sql)
        self.assertIn("DROP COLUMN IF EXISTS url_or_contents", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS file_url", sql)
        self.assertGreaterEqual(conn.savepoints, 1)

    def test_postgres_url_sets_pool_kwargs(self):
        import md_backend.utils.database as db
        from md_backend.utils.settings import settings

        spec = importlib.util.spec_from_file_location("isolated_database_config", db.__file__)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)

        with (
            patch.object(settings, "DATABASE_URL", "postgresql+asyncpg://u:p@host/db"),
            patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                return_value=MagicMock(),
            ) as create_engine_mock,
            patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=MagicMock()),
        ):
            spec.loader.exec_module(module)
            create_engine_mock.assert_called_once()
            kwargs = create_engine_mock.call_args.kwargs
            self.assertTrue(kwargs["pool_pre_ping"])
            self.assertEqual(kwargs["pool_recycle"], 1800)
            self.assertEqual(kwargs["pool_size"], 10)
            self.assertEqual(kwargs["max_overflow"], 20)
            self.assertNotIn("connect_args", kwargs)
            self.assertNotIn("poolclass", kwargs)
