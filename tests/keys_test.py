"""Default environment variables for tests."""

import os

DEFAULT_KEYS = {
    "TEST_VARIABLE": "test",
    "BASE_URL": "localhost",
    "DATABASE_URL": "sqlite+aiosqlite:///",
    "JWT_SECRET_KEY": "test-secret-key",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "30",
    "PASSWORD_PEPPER": "test-pepper",
}

for key, value in DEFAULT_KEYS.items():
    os.environ.setdefault(key, value)
