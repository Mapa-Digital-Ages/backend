"""Database connection and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from md_backend.models.db_models import Base
from md_backend.utils.settings import settings

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


async def _ensure_user_last_name_nullable(conn: AsyncConnection) -> None:
    """Drop the legacy NOT NULL constraint from user_profile.last_name."""
    if conn.dialect.name == "postgresql":
        await conn.execute(text("ALTER TABLE user_profile ALTER COLUMN last_name DROP NOT NULL"))


async def _migrate_resources_table(conn: AsyncConnection) -> None:
    """Apply schema updates to the resources table."""
    if conn.dialect.name != "postgresql":
        return

    # Create the enum type if it doesn't exist yet. Labels match the SQLAlchemy
    # enum (member names), which is how create_all emits this type.
    await conn.execute(
        text(
            "DO $$ BEGIN "
            "CREATE TYPE resource_type_enum AS ENUM "
            "('VIDEO','PDF','PRESENTATION','LINK','DOCUMENT'); "
            "EXCEPTION WHEN duplicate_object THEN NULL; "
            "END $$"
        )
    )

    # Rename contents_id → content_id only when the legacy column is still present
    # (a fresh create_all already produces content_id). Idempotent.
    await conn.execute(
        text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name='resources' AND column_name='contents_id') "
            "AND NOT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name='resources' AND column_name='content_id') "
            "THEN ALTER TABLE resources RENAME COLUMN contents_id TO content_id; "
            "END IF; END $$"
        )
    )

    # Convert the type column to the enum only while it is still varchar, mapping
    # legacy values (any case; 'text'/unknown → DOCUMENT) onto the enum labels.
    await conn.execute(
        text(
            "DO $$ BEGIN "
            "IF (SELECT data_type FROM information_schema.columns "
            "WHERE table_name='resources' AND column_name='type') <> 'USER-DEFINED' "
            "THEN ALTER TABLE resources ALTER COLUMN type TYPE resource_type_enum USING ("
            "CASE upper(type::text) "
            "WHEN 'VIDEO' THEN 'VIDEO' WHEN 'PDF' THEN 'PDF' "
            "WHEN 'PRESENTATION' THEN 'PRESENTATION' WHEN 'LINK' THEN 'LINK' "
            "WHEN 'DOCUMENT' THEN 'DOCUMENT' WHEN 'TEXT' THEN 'DOCUMENT' "
            "ELSE 'DOCUMENT' END)::resource_type_enum; "
            "END IF; END $$"
        )
    )

    # Drop the old url_or_contents column
    await conn.execute(text("ALTER TABLE resources DROP COLUMN IF EXISTS url_or_contents"))

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
        await conn.execute(text(stmt))


async def _migrate_sponsorship_tables(conn: AsyncConnection) -> None:
    """Apply schema updates for the sponsorship refactoring."""
    if conn.dialect.name != "postgresql":
        return

    # Create new enums if they do not exist
    for enum_name, enum_values in [
        ("request_status_enum", "('open','partially_fulfilled','fulfilled','cancelled')"),
        ("partnership_status_enum", "('pending','approved','rejected')"),
    ]:
        await conn.execute(
            text(
                f"DO $$ BEGIN CREATE TYPE {enum_name} AS ENUM {enum_values}; "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            )
        )

    # Drop legacy columns from user profiles (if they exist)
    await conn.execute(text("ALTER TABLE school_profile DROP COLUMN IF EXISTS requested_spots"))
    await conn.execute(text("ALTER TABLE company_profile DROP COLUMN IF EXISTS available_spots"))

    # Refactor SchoolCompanyPartnership table (we can just let create_all recreate it if we drop,
    # or handle dropping the old composite PK and adding the new UUID PK if the table exists).
    # Since we are adding new UUID PKs and removing the composite PK, the simplest manual
    # migration in dev environment is to drop and let create_all recreate it,
    # or alter it directly. We'll try to alter it if we want to preserve data, but since the
    # previous schema had no UUID `id` or `request_id`, it's complex.
    # To be safe and idempotent, we'll try to add the `id` column. If it fails, we assume it's done.
    try:
        await conn.execute(
            text(
                "ALTER TABLE school_company_partnership "
                "DROP CONSTRAINT school_company_partnership_pkey"
            )
        )
    except Exception:
        pass

    for stmt in [
        "ALTER TABLE school_company_partnership ADD COLUMN IF NOT EXISTS "
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid()",
        "ALTER TABLE school_company_partnership ADD COLUMN IF NOT EXISTS request_id UUID NULL",
        "ALTER TABLE school_company_partnership ADD COLUMN IF NOT EXISTS "
        "granted_spots INTEGER NULL",
    ]:
        try:
            await conn.execute(text(stmt))
        except Exception:
            pass

    try:
        await conn.execute(
            text(
                "ALTER TABLE school_company_partnership ADD COLUMN IF NOT EXISTS "
                "status partnership_status_enum NOT NULL DEFAULT 'pending'"
            )
        )
    except Exception:
        pass


async def init_db() -> None:
    """Create all database tables and apply lightweight schema compatibility fixes."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_user_last_name_nullable(conn)
        await _migrate_resources_table(conn)
        await _migrate_sponsorship_tables(conn)
