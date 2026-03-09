"""Tests for the main app entry point."""

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from md_backend.main import app
from tests.keys_test import DEFAULT_KEYS

for key, value in DEFAULT_KEYS.items():
    os.environ.setdefault(key, value)


class TestMain(unittest.TestCase):
    def setUp(self):
        """Setup method to initialize the TestClient."""
        self.test_client = TestClient(app)

    def test_root_endpoint(self):
        """Test the root endpoint."""
        response = self.test_client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({"detail": "Alive!"}, response.json())
