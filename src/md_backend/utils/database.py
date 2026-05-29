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

    # Create the enum type if it doesn't exist yet
    await conn.execute(
        text(
            "DO $$ BEGIN "
            "CREATE TYPE resource_type_enum AS ENUM "
            "('video','pdf','presentation','link','document'); "
            "EXCEPTION WHEN duplicate_object THEN NULL; "
            "END $$"
        )
    )

    # Rename contents_id → content_id
    await conn.execute(
        text(
            "ALTER TABLE resources RENAME COLUMN contents_id TO content_id"
        )
    )

    # Convert type column from varchar to resource_type_enum
    await conn.execute(
        text(
            "ALTER TABLE resources "
            "ALTER COLUMN type TYPE resource_type_enum USING type::resource_type_enum"
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
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        "ALTER TABLE resources ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    ]:
        await conn.execute(text(stmt))


async def init_db() -> None:
    """Create all database tables and apply lightweight schema compatibility fixes."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_user_last_name_nullable(conn)
        await _migrate_resources_table(conn)

