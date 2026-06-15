"""Guard: trail seeding is gone and /setup no longer crashes on it."""

import os
import unittest

from fastapi.testclient import TestClient

import tests.keys_test  # noqa: F401
from md_backend.main import app

_SETUP_HEADERS = {"X-Setup-Token": os.environ.get("SETUP_TOKEN", "")}


class TestTrailSeedRemoved(unittest.TestCase):
    def test_seed_default_trails_is_not_importable(self):
        import md_backend.services.path_service as ps

        self.assertFalse(
            hasattr(ps, "seed_default_trails"),
            "seed_default_trails must be removed (content comes from external pipeline)",
        )

    def test_setup_endpoint_does_not_500(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/setup",
                json={
                    "email": "boot@example.com",
                    "password": "securepass123",
                    "first_name": "Boot",
                    "last_name": "Strap",
                    "phone_number": "+5551999999999",
                },
                headers=_SETUP_HEADERS,
            )
            self.assertIn(resp.status_code, (201, 409))
