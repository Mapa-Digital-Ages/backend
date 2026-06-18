"""Database connection and session management."""

import logging
from collections.abc import AsyncGenerator
from typing import cast

from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from md_backend.models.db_models import Base, StudentSubPathItemProgress
from md_backend.utils.settings import settings

logger = logging.getLogger(__name__)

_engine_kwargs: dict = {"echo": False}
if settings.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine_kwargs["poolclass"] = StaticPool
else:
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 1800
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for FastAPI dependency injection."""
    async with AsyncSessionLocal() as session:
        yield session


async def _execute_optional_ddl(conn: AsyncConnection, stmt: str) -> None:
    """Execute optional PostgreSQL DDL without aborting the outer transaction."""
    try:
        async with conn.begin_nested():
            await conn.execute(text(stmt))
    except Exception:
        logger.debug("Optional schema migration statement failed: %s", stmt, exc_info=True)


async def _ensure_user_last_name_nullable(conn: AsyncConnection) -> None:
    """Drop the legacy NOT NULL constraint from user_profile.last_name."""
    if conn.dialect.name == "postgresql":
        await _execute_optional_ddl(
            conn, "ALTER TABLE user_profile ALTER COLUMN last_name DROP NOT NULL"
        )


async def _migrate_resources_table(conn: AsyncConnection) -> None:
    """Apply schema updates to the resources table."""
    if conn.dialect.name != "postgresql":
        return

    # Create the enum type if it doesn't exist yet. Labels match the SQLAlchemy
    # enum (member names), which is how create_all emits this type.
    await _execute_optional_ddl(
        conn,
        "DO $$ BEGIN "
        "CREATE TYPE resource_type_enum AS ENUM "
        "('VIDEO','PDF','PRESENTATION','LINK','DOCUMENT'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$",
    )

    # Rename contents_id → content_id only when the legacy column is still present
    # (a fresh create_all already produces content_id). Idempotent.
    await _execute_optional_ddl(
        conn,
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name='resources' AND column_name='contents_id') "
        "AND NOT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name='resources' AND column_name='content_id') "
        "THEN ALTER TABLE resources RENAME COLUMN contents_id TO content_id; "
        "END IF; END $$",
    )

    # Convert the type column to the enum only while it is still varchar, mapping
    # legacy values (any case; 'text'/unknown → DOCUMENT) onto the enum labels.
    await _execute_optional_ddl(
        conn,
        "DO $$ BEGIN "
        "IF (SELECT data_type FROM information_schema.columns "
        "WHERE table_name='resources' AND column_name='type') <> 'USER-DEFINED' "
        "THEN ALTER TABLE resources ALTER COLUMN type TYPE resource_type_enum USING ("
        "CASE upper(type::text) "
        "WHEN 'VIDEO' THEN 'VIDEO' WHEN 'PDF' THEN 'PDF' "
        "WHEN 'PRESENTATION' THEN 'PRESENTATION' WHEN 'LINK' THEN 'LINK' "
        "WHEN 'DOCUMENT' THEN 'DOCUMENT' WHEN 'TEXT' THEN 'DOCUMENT' "
        "ELSE 'DOCUMENT' END)::resource_type_enum; "
        "END IF; END $$",
    )

    # Drop the old url_or_contents column
    await _execute_optional_ddl(conn, "ALTER TABLE resources DROP COLUMN IF EXISTS url_or_contents")

    # Add new file metadata columns
    for stmt in [
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS file_name VARCHAR(255) NULL",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS file_type VARCHAR(100) NULL",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT NULL",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS storage_key VARCHAR(255) NULL",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS file_url VARCHAR(1024) NOT NULL DEFAULT ''",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    ]:
        await _execute_optional_ddl(conn, stmt)


async def _migrate_sponsorship_tables(conn: AsyncConnection) -> None:
    """Apply schema updates for the sponsorship refactoring."""
    if conn.dialect.name != "postgresql":
        return

    # Create new enums if they do not exist
    for enum_name, enum_values in [
        (
            "sponsorship_request_status_enum",
            "('OPEN','PARTIALLY_FULFILLED','FULFILLED','CANCELLED')",
        ),
        ("partnership_status_enum", "('PENDING','APPROVED','REJECTED')"),
    ]:
        await _execute_optional_ddl(
            conn,
            f"DO $$ BEGIN CREATE TYPE {enum_name} AS ENUM {enum_values}; "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        )

    # Keep existing databases aligned with the current ORM models.
    await _execute_optional_ddl(
        conn, "ALTER TABLE school_profile ADD COLUMN IF NOT EXISTS requested_spots INTEGER NULL"
    )
    await _execute_optional_ddl(
        conn,
        "ALTER TABLE sponsorship_request ADD COLUMN IF NOT EXISTS "
        "title VARCHAR(255) NOT NULL DEFAULT ''",
    )
    await _execute_optional_ddl(
        conn, "ALTER TABLE sponsorship_request ADD COLUMN IF NOT EXISTS description TEXT NULL"
    )
    await _execute_optional_ddl(
        conn,
        "ALTER TABLE company_profile ADD COLUMN IF NOT EXISTS "
        "available_spots INTEGER NOT NULL DEFAULT 0",
    )

    # Refactor SchoolCompanyPartnership table. These compatibility statements may fail on
    # already-migrated databases, so each one runs inside a savepoint. PostgreSQL marks the
    # whole transaction as aborted after a failed statement unless the savepoint is rolled back.
    for stmt in [
        "ALTER TABLE school_company_partnership ADD COLUMN IF NOT EXISTS id UUID "
        "DEFAULT gen_random_uuid()",
        "UPDATE school_company_partnership SET id = gen_random_uuid() WHERE id IS NULL",
        "ALTER TABLE school_company_partnership ADD COLUMN IF NOT EXISTS request_id UUID NULL",
        "ALTER TABLE school_company_partnership ADD COLUMN IF NOT EXISTS "
        "granted_spots INTEGER NULL",
        "ALTER TABLE school_company_partnership ADD COLUMN IF NOT EXISTS "
        "is_active BOOLEAN NOT NULL DEFAULT true",
        "ALTER TABLE school_company_partnership ADD COLUMN IF NOT EXISTS "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        "ALTER TABLE school_company_partnership ADD COLUMN IF NOT EXISTS "
        "deactivated_at TIMESTAMPTZ NULL",
    ]:
        await _execute_optional_ddl(conn, stmt)

    await _execute_optional_ddl(
        conn,
        "DO $$ DECLARE "
        "rel oid := to_regclass('school_company_partnership'); "
        "id_attnum smallint; "
        "BEGIN "
        "IF rel IS NULL THEN RETURN; END IF; "
        "SELECT attnum INTO id_attnum FROM pg_attribute "
        "WHERE attrelid = rel AND attname = 'id' AND NOT attisdropped; "
        "IF id_attnum IS NULL THEN RETURN; END IF; "
        "IF NOT EXISTS ("
        "SELECT 1 FROM pg_constraint "
        "WHERE conrelid = rel AND contype IN ('p', 'u') AND conkey = ARRAY[id_attnum]"
        ") THEN "
        "ALTER TABLE school_company_partnership "
        "ADD CONSTRAINT school_company_partnership_id_key UNIQUE (id); "
        "END IF; "
        "END $$",
    )

    await _execute_optional_ddl(
        conn,
        "ALTER TABLE school_company_partnership ADD COLUMN IF NOT EXISTS "
        "status partnership_status_enum NOT NULL DEFAULT 'PENDING'",
    )


async def _ensure_item_progress_table(conn: AsyncConnection) -> None:
    """Create item-level progress table for existing databases."""
    table = cast(Table, StudentSubPathItemProgress.__table__)
    await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))


async def init_db() -> None:
    """Create all database tables and apply lightweight schema compatibility fixes."""
    async with engine.begin() as conn:
        await _migrate_sponsorship_tables(conn)
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_item_progress_table(conn)
        await _ensure_user_last_name_nullable(conn)
        await _migrate_resources_table(conn)
        await _migrate_sponsorship_tables(conn)
        await _ensure_user_last_name_nullable(conn)
