"""Default environment variables for tests."""

import os

DEFAULT_KEYS = {
    "TEST_VARIABLE": "test",
    "BASE_URL": "localhost",
    "DATABASE_URL": "sqlite+aiosqlite:///",
    "JWT_SECRET_KEY": "test-secret-key-for-unit-tests-only-32c",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "30",
    "PASSWORD_PEPPER": "test-pepper-for-unit-tests-only-32chars",
    "RATE_LIMIT_ENABLED": "false",
}

for key, value in DEFAULT_KEYS.items():
    os.environ[key] = value
