"""Pytest configuration: set environment variables before any test module is imported."""

import os

from tests.keys_test import DEFAULT_KEYS

for key, value in DEFAULT_KEYS.items():
    os.environ.setdefault(key, value)
