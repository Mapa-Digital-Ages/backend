import os

DEFAULT_KEYS = {"TEST_VARIABLE": "test", "BASE_URL": "localhost"}

for key, value in DEFAULT_KEYS.items():
    os.environ.setdefault(key, value)
