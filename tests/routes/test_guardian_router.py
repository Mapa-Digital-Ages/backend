"""Integration tests for guardian endpoints."""

import asyncio
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from md_backend.main import app
from md_backend.models.db_models import StudentGuardian, UserProfile
from md_backend.utils.database import AsyncSessionLocal
from tests.helpers import get_admin_headers


class TestGuardianRouterIntegration(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app, raise_server_exceptions=False)
        self.client = self.ctx.__enter__()
        self.admin_headers = get_admin_headers(self.client)

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def _run_async(self, coro):
        return asyncio.run(coro)

    async def _mark_user_inactive(self, user_id: str) -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.id == user_id)
            )
            user = result.scalar_one_or_none()
            if user is not None:
                user.is_active = False
                await session.commit()

    async def _link_student_to_guardian(self, student_id: str, guardian_id: str) -> None:
        async with AsyncSessionLocal() as session:
            session.add(
                StudentGuardian(student_id=uuid.UUID(student_id), guardian_id=uuid.UUID(guardian_id))
            )
            await session.commit()

    def test_list_guardians_returns_active_guardians(self):
        guardian_response = self.client.post(
            "/register/responsavel",
            json={"email": "guard_active@example.com", "password": "validpass123", "name": "Guard A"},
        )
        guardian_id = guardian_response.json()["id"]

        self.client.patch(
            f"/admin/users/{guardian_id}/status",
            json={"status": "aprovado"},
            headers=self.admin_headers,
        )

        response = self.client.get("/guardians", headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertTrue(any(item["id"] == guardian_id for item in items))
        for item in items:
            self.assertNotIn("password", item)

    def test_list_guardians_filters_by_status_and_name(self):
        guardian_response = self.client.post(
            "/register/responsavel",
            json={"email": "guard_filter@example.com", "password": "validpass123", "name": "Filter Guard"},
        )
        guardian_id = guardian_response.json()["id"]

        self.client.patch(
            f"/admin/users/{guardian_id}/status",
            json={"status": "aprovado"},
            headers=self.admin_headers,
        )

        response = self.client.get(
            "/guardians",
            params={"name": "Filter", "status": "approved"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertTrue(any(item["id"] == guardian_id for item in items))

    def test_get_guardian_by_id_returns_students(self):
        guardian_response = self.client.post(
            "/register/responsavel",
            json={"email": "guard_students@example.com", "password": "validpass123", "name": "Student Guard"},
        )
        guardian_id = guardian_response.json()["id"]

        self.client.patch(
            f"/admin/users/{guardian_id}/status",
            json={"status": "aprovado"},
            headers=self.admin_headers,
        )

        student_response = self.client.post(
            "/student",
            json={
                "first_name": "Aluno",
                "last_name": "Link",
                "email": "student_link@example.com",
                "password": "securepass123",
                "birth_date": "2010-05-20",
                "student_class": "5th class",
            },
            headers=self.admin_headers,
        )
        student_id = student_response.json()["user_id"]

        self._run_async(self._link_student_to_guardian(student_id, guardian_id))

        response = self.client.get(f"/guardians/{guardian_id}", headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], guardian_id)
        self.assertIn("students", body)
        self.assertEqual(body["students"], [student_id])

    def test_inactive_guardians_do_not_appear_in_list(self):
        active_response = self.client.post(
            "/register/responsavel",
            json={"email": "guard_active2@example.com", "password": "validpass123", "name": "Active Guard"},
        )
        self.client.patch(
            f"/admin/users/{active_response.json()["id"]}/status",
            json={"status": "aprovado"},
            headers=self.admin_headers,
        )

        inactive_response = self.client.post(
            "/register/responsavel",
            json={"email": "guard_inactive@example.com", "password": "validpass123", "name": "Inactive Guard"},
        )
        inactive_id = inactive_response.json()["id"]
        self.client.patch(
            f"/admin/users/{inactive_id}/status",
            json={"status": "aprovado"},
            headers=self.admin_headers,
        )
        self._run_async(self._mark_user_inactive(inactive_id))

        response = self.client.get("/guardians", headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.json()]
        self.assertNotIn(inactive_id, ids)

    def test_get_guardian_not_found_returns_404(self):
        response = self.client.get(
            f"/guardians/{uuid.uuid4()}", headers=self.admin_headers
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Responsavel nao encontrado")
