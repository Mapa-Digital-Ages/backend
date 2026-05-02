"""Tests for the register router."""

import asyncio
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

import tests.keys_test  # noqa: F401
from md_backend.main import app
from md_backend.models.db_models import StudentProfile, UserProfile
from md_backend.utils.database import AsyncSessionLocal


def _guardian_payload(email, **overrides):
    payload = {
        "email": email,
        "password": "validpass123",
        "first_name": "New",
        "last_name": "User",
    }
    payload.update(overrides)
    return payload


def _student_payload(email, **overrides):
    payload = {
        "email": email,
        "password": "validpass123",
        "first_name": "Stu",
        "last_name": "Dent",
        "birth_date": "2010-05-01",
        "student_class": "5th class",
    }
    payload.update(overrides)
    return payload


class TestRegisterRouter(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.test_client = self.ctx.__enter__()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_register_guardian_success(self):
        response = self.test_client.post(
            "/register/guardian", json=_guardian_payload("newuser@test.com")
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["detail"], "Registration completed. Awaiting approval.")
        self.assertIn("id", body)

    def test_register_guardian_with_phone_number_persists(self):
        email = "guardian_phone@test.com"
        response = self.test_client.post(
            "/register/guardian",
            json=_guardian_payload(email, phone_number="+5511999998888"),
        )
        self.assertEqual(response.status_code, 201)

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.email == email)
                )
                return result.scalar_one()

        user = asyncio.run(fetch())
        self.assertEqual(user.phone_number, "+5511999998888")
        self.assertEqual(user.first_name, "New")
        self.assertEqual(user.last_name, "User")

    def test_register_guardian_without_phone_number_persists_null(self):
        email = "guardian_no_phone@test.com"
        response = self.test_client.post(
            "/register/guardian", json=_guardian_payload(email)
        )
        self.assertEqual(response.status_code, 201)

        async def fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.email == email)
                )
                return result.scalar_one()

        user = asyncio.run(fetch())
        self.assertIsNone(user.phone_number)

    def test_register_guardian_duplicate_email(self):
        self.test_client.post(
            "/register/guardian", json=_guardian_payload("duplicate@test.com")
        )
        response = self.test_client.post(
            "/register/guardian", json=_guardian_payload("duplicate@test.com")
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Email already registered"})

    def test_register_guardian_invalid_email(self):
        response = self.test_client.post(
            "/register/guardian", json=_guardian_payload("not-an-email")
        )
        self.assertEqual(response.status_code, 422)

    def test_register_guardian_short_password(self):
        response = self.test_client.post(
            "/register/guardian", json=_guardian_payload("short@test.com", password="short")
        )
        self.assertEqual(response.status_code, 422)

    def test_register_guardian_missing_first_name(self):
        payload = _guardian_payload("missing_first@test.com")
        del payload["first_name"]
        response = self.test_client.post("/register/guardian", json=payload)
        self.assertEqual(response.status_code, 422)

    def test_register_guardian_missing_last_name(self):
        payload = _guardian_payload("missing_last@test.com")
        del payload["last_name"]
        response = self.test_client.post("/register/guardian", json=payload)
        self.assertEqual(response.status_code, 422)

    def test_register_student_success(self):
        response = self.test_client.post(
            "/register/student", json=_student_payload("student@test.com")
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["detail"], "Registration completed.")
        self.assertIn("id", body)

    def test_register_student_with_optional_fields_persists(self):
        school_resp = self.test_client.post(
            "/school",
            json={
                "first_name": "School",
                "last_name": "Host",
                "email": "register_student_school@test.com",
                "password": "password1234",
                "is_private": True,
            },
        )
        school_id = school_resp.json()["user_id"]

        email = "student_optional@test.com"
        response = self.test_client.post(
            "/register/student",
            json=_student_payload(
                email, phone_number="+5511777776666", school_id=school_id
            ),
        )
        self.assertEqual(response.status_code, 201)

        async def fetch():
            async with AsyncSessionLocal() as session:
                user_row = await session.execute(
                    select(UserProfile).where(UserProfile.email == email)
                )
                user = user_row.scalar_one()
                student_row = await session.execute(
                    select(StudentProfile).where(StudentProfile.user_id == user.id)
                )
                return user, student_row.scalar_one()

        user, student = asyncio.run(fetch())
        self.assertEqual(user.phone_number, "+5511777776666")
        self.assertEqual(student.school_id, uuid.UUID(school_id))

    def test_register_student_without_optional_fields_persists_null(self):
        email = "student_no_optional@test.com"
        response = self.test_client.post(
            "/register/student", json=_student_payload(email)
        )
        self.assertEqual(response.status_code, 201)

        async def fetch():
            async with AsyncSessionLocal() as session:
                user_row = await session.execute(
                    select(UserProfile).where(UserProfile.email == email)
                )
                user = user_row.scalar_one()
                student_row = await session.execute(
                    select(StudentProfile).where(StudentProfile.user_id == user.id)
                )
                return user, student_row.scalar_one()

        user, student = asyncio.run(fetch())
        self.assertIsNone(user.phone_number)
        self.assertIsNone(student.school_id)

    def test_register_student_duplicate_email(self):
        payload = _student_payload("dup_student@test.com")
        self.test_client.post("/register/student", json=payload)
        response = self.test_client.post("/register/student", json=payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Email already registered"})

    def test_register_student_missing_required_fields(self):
        response = self.test_client.post(
            "/register/student",
            json={
                "email": "incomplete@test.com",
                "password": "validpass123",
                "first_name": "Inc",
                "last_name": "Omplete",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_register_student_invalid_class(self):
        response = self.test_client.post(
            "/register/student",
            json=_student_payload("badclass@test.com", student_class="10th class"),
        )
        self.assertEqual(response.status_code, 422)
