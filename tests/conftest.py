"""Pytest configuration: set environment variables before any test module is imported."""

import asyncio
import os

import pytest

from tests.keys_test import DEFAULT_KEYS

for key, value in DEFAULT_KEYS.items():
    os.environ.setdefault(key, value)


@pytest.fixture(scope="session", autouse=True)
def _dispose_engine():
    """Dispose the async engine after all tests so aiosqlite connections close cleanly."""
    yield
    from md_backend.utils.database import engine

    asyncio.run(engine.dispose())
