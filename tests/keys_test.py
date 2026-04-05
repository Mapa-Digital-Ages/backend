import os

DEFAULT_KEYS = {
    "TEST_VARIABLE": "test",
    "BASE_URL": "localhost",
    "ADMIN_EMAIL": "admin@test.com",
    "ADMIN_PASSWORD": "secret"}

for key, value in DEFAULT_KEYS.items():
    os.environ.setdefault(key, value)
