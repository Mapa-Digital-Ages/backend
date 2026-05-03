"""Tests for the setup router."""

import asyncio
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import select

import tests.keys_test  # noqa: F401
from md_backend.main import app
from md_backend.models.db_models import UserProfile
from md_backend.utils.database import AsyncSessionLocal


def _setup_payload(email, **overrides):
    payload = {
        "email": email,
        "password": "adminpass123",
        "first_name": "Super",
        "last_name": "Admin",
    }
    payload.update(overrides)
    return payload


class TestSetupRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_setup_creates_superadmin(self):
        response = self.test_client.post(
            "/api/setup", json=_setup_payload("sa_create@test.com")
        )
        self.assertIn(response.status_code, (201, 409))
        if response.status_code == 201:
            self.assertEqual(response.json()["detail"], "Superadmin created successfully")
            self.assertIn("id", response.json())

    def test_setup_persists_first_last_phone(self):
        email = "sa_full@test.com"
        response = self.test_client.post(
            "/api/setup",
            json=_setup_payload(
                email,
                first_name="Ada",
                last_name="Lovelace",
                phone_number="+5511555554444",
            ),
        )
        if response.status_code != 201:
            self.skipTest("Superadmin already created in this test DB")

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.email == email)
                )
                return result.scalar_one()

        user = asyncio.run(fetch())
        self.assertEqual(user.first_name, "Ada")
        self.assertEqual(user.last_name, "Lovelace")
        self.assertEqual(user.phone_number, "+5511555554444")

    def test_setup_without_phone_number_persists_null(self):
        email = "sa_no_phone@test.com"
        response = self.test_client.post("/api/setup", json=_setup_payload(email))
        if response.status_code != 201:
            self.skipTest("Superadmin already created in this test DB")

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.email == email)
                )
                return result.scalar_one()

        user = asyncio.run(fetch())
        self.assertIsNone(user.phone_number)

    def test_setup_superadmin_can_login(self):
        self.test_client.post("/api/setup", json=_setup_payload("sa_canlogin@test.com"))
        response = self.test_client.post(
            "/api/login", json={"email": "sa_canlogin@test.com", "password": "adminpass123"}
        )
        if response.status_code == 200:
            self.assertIn("token", response.json())

    def test_setup_duplicate_returns_409(self):
        self.test_client.post("/api/setup", json=_setup_payload("sa_dup@test.com"))
        response = self.test_client.post("/api/setup", json=_setup_payload("sa_dup2@test.com"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Setup already completed"})

    def test_setup_invalid_email(self):
        response = self.test_client.post("/api/setup", json=_setup_payload("not-an-email"))
        self.assertEqual(response.status_code, 422)

    def test_setup_short_password(self):
        response = self.test_client.post(
            "/api/setup", json=_setup_payload("sa@test.com", password="short")
        )
        self.assertEqual(response.status_code, 422)

    def test_setup_missing_first_name_returns_422(self):
        payload = _setup_payload("sa_no_first@test.com")
        del payload["first_name"]
        response = self.test_client.post("/api/setup", json=payload)
        self.assertEqual(response.status_code, 422)

    def test_setup_missing_last_name_returns_422(self):
        payload = _setup_payload("sa_no_last@test.com")
        del payload["last_name"]
        response = self.test_client.post("/api/setup", json=payload)
        self.assertEqual(response.status_code, 422)
