"""Integration tests for the calendar upsert endpoint (soft delete)."""

import datetime
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

import tests.keys_test  # noqa: F401
from md_backend.main import app
from md_backend.models.db_models import Subject, Task
from md_backend.utils.database import get_db_session
from tests.helpers import get_admin_headers


def _student_payload(email):
    return {
        "first_name": "Calendar",
        "last_name": "Test",
        "email": email,
        "password": "securepass123",
        "birth_date": "2010-05-20",
        "student_class": "5th class",
    }


def _login_token(client, email, password="securepass123"):
    return client.post("/api/login", json={"email": email, "password": password}).json()["token"]


def _create_student(client, admin_headers, email=None):
    email = email or f"cal_student_{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/api/student", json=_student_payload(email), headers=admin_headers)
    student_id = resp.json()["user_id"]
    token = _login_token(client, email)
    return student_id, token


def _ensure_subject(session_factory) -> int:
    """Return an existing subject ID or create one."""
    import asyncio

    async def _run():
        async for session in session_factory():
            result = await session.execute(select(Subject).limit(1))
            subject = result.scalar_one_or_none()
            if subject is None:
                subject = Subject(name=f"Matemática_{uuid.uuid4().hex[:4]}")
                session.add(subject)
                await session.commit()
                await session.refresh(subject)
            return subject.id

    return asyncio.run(_run())


class TestCalendarSoftDelete(unittest.TestCase):
    """Integration tests for PUT /student/{id}/calendar/{date}."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.admin_headers = get_admin_headers(cls.client)
        cls.subject_id = _ensure_subject(get_db_session)

    def _upsert(self, student_id, date_str, tasks, headers):
        return self.client.put(
            f"/api/student/{student_id}/calendar/{date_str}",
            json={"tasks": tasks},
            headers=headers,
        )

    def _get_day(self, student_id, date_str, headers):
        return self.client.get(
            f"/api/student/{student_id}/calendar/{date_str}",
            headers=headers,
        )

    def test_soft_deletes_omitted_task(self):
        """Insert 3 tasks, resync with 2 → the 3rd must have deactivated_at set."""
        student_id, _ = _create_student(self.client, self.admin_headers)
        date_str = "2024-09-10"

        task_payload = [
            {"title": "Tarefa A", "subject_id": self.subject_id, "task_status": "pending"},
            {"title": "Tarefa B", "subject_id": self.subject_id, "task_status": "pending"},
            {"title": "Tarefa C", "subject_id": self.subject_id, "task_status": "pending"},
        ]
        resp = self._upsert(student_id, date_str, task_payload, self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        tasks_after_insert = resp.json()
        self.assertEqual(len(tasks_after_insert), 3)

        id_a = next(t["id"] for t in tasks_after_insert if t["title"] == "Tarefa A")
        id_b = next(t["id"] for t in tasks_after_insert if t["title"] == "Tarefa B")

        payload_with_two = [
            {"id": id_a, 
             "title": "Tarefa A", 
             "subject_id": self.subject_id, 
             "task_status": "pending"},
            
            {"id": id_b, 
             "title": "Tarefa B", 
             "subject_id": self.subject_id, 
             "task_status": "pending"},
        ]
        resp2 = self._upsert(student_id, date_str, payload_with_two, self.admin_headers)
        self.assertEqual(resp2.status_code, 200)
        remaining = resp2.json()
        self.assertEqual(len(remaining), 2)

        titles = {t["title"] for t in remaining}
        self.assertIn("Tarefa A", titles)
        self.assertIn("Tarefa B", titles)
        self.assertNotIn("Tarefa C", titles)

    def test_soft_deleted_task_not_returned_by_get(self):
        """After soft-delete, GET /calendar/{date} must not return the deleted task."""
        student_id, _ = _create_student(self.client, self.admin_headers)
        date_str = "2024-09-11"

        resp = self._upsert(
            student_id,
            date_str,
            [
                {"title": "Keep", "subject_id": self.subject_id, "task_status": None},
                {"title": "Delete me", "subject_id": self.subject_id, "task_status": None},
            ],
            self.admin_headers,
        )
        self.assertEqual(resp.status_code, 200)
        all_tasks = resp.json()
        keep_id = next(t["id"] for t in all_tasks if t["title"] == "Keep")

        self._upsert(
            student_id,
            date_str,
            [{"id": keep_id, "title": "Keep", "subject_id": self.subject_id, "task_status": None}],
            self.admin_headers,
        )

        get_resp = self._get_day(student_id, date_str, self.admin_headers)
        self.assertEqual(get_resp.status_code, 200)
        titles = [t["title"] for t in get_resp.json()]
        self.assertIn("Keep", titles)
        self.assertNotIn("Delete me", titles)

    def test_deactivated_at_is_set_in_db(self):
        """Verify deactivated_at is non-null in the DB for the soft-deleted task."""
        import asyncio

        student_id, _ = _create_student(self.client, self.admin_headers)
        date_str = "2024-09-12"

        resp = self._upsert(
            student_id,
            date_str,
            [
                {"title": "Active", "subject_id": self.subject_id, "task_status": None},
                {"title": "Deactivated", "subject_id": self.subject_id, "task_status": None},
            ],
            self.admin_headers,
        )
        all_tasks = resp.json()
        active_id = next(t["id"] for t in all_tasks if t["title"] == "Active")
        deactivated_id = next(t["id"] for t in all_tasks if t["title"] == "Deactivated")

        self._upsert(
            student_id,
            date_str,
            [{"id": active_id, 
              "title": "Active", 
              "subject_id": self.subject_id, 
              "task_status": None}],
            self.admin_headers,
        )

        async def _check():
            async for session in get_db_session():
                result = await session.execute(select(Task).where(Task.id == deactivated_id))
                task = result.scalar_one_or_none()
                return task

        task = asyncio.run(_check())
        self.assertIsNotNone(task)
        self.assertIsNotNone(task.deactivated_at)

    def test_upsert_empty_array_deactivates_all(self):
        """Sending an empty array must soft-delete all tasks for that day."""
        student_id, _ = _create_student(self.client, self.admin_headers)
        date_str = "2024-09-13"

        self._upsert(
            student_id,
            date_str,
            [{"title": "Task X", "subject_id": self.subject_id, "task_status": None}],
            self.admin_headers,
        )

        resp = self._upsert(student_id, date_str, [], self.admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_upsert_access_denied_for_unrelated_student(self):
        """A student must not be able to upsert another student's calendar."""
        target_id, _ = _create_student(self.client, self.admin_headers)
        _, requester_token = _create_student(self.client, self.admin_headers)
        requester_headers = {"Authorization": f"Bearer {requester_token}"}

        resp = self._upsert(target_id, "2024-09-14", [], requester_headers)
        self.assertEqual(resp.status_code, 403)
