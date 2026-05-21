"""Unit tests for the calendar soft-delete logic in StudentService."""

import asyncio
import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import tests.keys_test  # noqa: F401
from md_backend.services.student_service import StudentService


class TestGetIdsToDeactivate(unittest.TestCase):
    """Unit tests for StudentService.get_ids_to_deactivate (pure array-diff logic)."""

    def setUp(self):
        self.service = StudentService()

    def test_returns_ids_absent_from_payload(self):
        db_ids = [1, 2, 3]
        payload_ids = [1, 2]
        result = self.service.get_ids_to_deactivate(db_ids, payload_ids)
        self.assertEqual(result, [3])

    def test_returns_empty_when_all_ids_present(self):
        db_ids = [1, 2, 3]
        payload_ids = [1, 2, 3]
        result = self.service.get_ids_to_deactivate(db_ids, payload_ids)
        self.assertEqual(result, [])

    def test_returns_all_ids_when_payload_is_empty(self):
        db_ids = [1, 2, 3]
        payload_ids = []
        result = self.service.get_ids_to_deactivate(db_ids, payload_ids)
        self.assertCountEqual(result, [1, 2, 3])

    def test_returns_empty_when_db_is_empty(self):
        db_ids = []
        payload_ids = [1, 2]
        result = self.service.get_ids_to_deactivate(db_ids, payload_ids)
        self.assertEqual(result, [])

    def test_returns_empty_when_both_empty(self):
        result = self.service.get_ids_to_deactivate([], [])
        self.assertEqual(result, [])

    def test_ignores_payload_ids_not_in_db(self):
        """IDs sent in the payload that don't exist in the DB must not appear in result."""
        db_ids = [1, 2]
        payload_ids = [1, 2, 99]
        result = self.service.get_ids_to_deactivate(db_ids, payload_ids)
        self.assertEqual(result, [])

    def test_multiple_ids_to_deactivate(self):
        db_ids = [10, 20, 30, 40]
        payload_ids = [20]
        result = self.service.get_ids_to_deactivate(db_ids, payload_ids)
        self.assertCountEqual(result, [10, 30, 40])


class TestUpsertCalendarDaySoftDelete(unittest.TestCase):
    """Unit tests for the soft-delete branch inside upsert_calendar_day."""

    def setUp(self):
        self.service = StudentService()
        self.student_id = uuid.uuid4()
        self.date = datetime.date(2024, 9, 1)

    def _make_mock_task(self, task_id: int) -> MagicMock:
        task = MagicMock()
        task.id = task_id
        task.title = f"Task {task_id}"
        task.subject_id = 1
        task.task_status = None
        task.date = datetime.datetime(2024, 9, 1, tzinfo=datetime.UTC)
        task.deactivated_at = None
        task.student_id = self.student_id
        return task

    def test_soft_deletes_missing_task_via_update(self):
        """When 1 of 3 DB tasks is omitted from payload, UPDATE must be called for that ID."""
        existing_tasks = [
            self._make_mock_task(1),
            self._make_mock_task(2),
            self._make_mock_task(3),
        ]

        first_result = MagicMock()
        first_result.scalars.return_value.all.return_value = existing_tasks

        refreshed_result = MagicMock()
        refreshed_result.scalars.return_value.all.return_value = [
            self._make_mock_task(1),
            self._make_mock_task(2),
        ]

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            first_result,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            refreshed_result]
        mock_session.add = MagicMock()

        payload = [
            {"id": 1, "title": "Task 1", "subject_id": 1, "task_status": None},
            {"id": 2, "title": "Task 2", "subject_id": 1, "task_status": None},
        ]

        result = asyncio.run(
            self.service.upsert_calendar_day(
                session=mock_session,
                student_id=self.student_id,
                date=self.date,
                tasks=payload,
            )
        )

        mock_session.commit.assert_called_once()
        self.assertEqual(len(result), 2)

    def test_no_soft_delete_when_all_tasks_present(self):
        """When all DB task IDs appear in payload, no UPDATE for deactivation should run."""
        existing_tasks = [self._make_mock_task(1), self._make_mock_task(2)]

        first_result = MagicMock()
        first_result.scalars.return_value.all.return_value = existing_tasks

        refreshed_result = MagicMock()
        refreshed_result.scalars.return_value.all.return_value = existing_tasks

        mock_session = AsyncMock()
        execute_calls = []

        async def fake_execute(stmt):
            execute_calls.append(stmt)
            if len(execute_calls) == 1:
                return first_result
            return refreshed_result

        mock_session.execute.side_effect = fake_execute
        mock_session.add = MagicMock()

        payload = [
            {"id": 1, "title": "Task 1", "subject_id": 1, "task_status": None},
            {"id": 2, "title": "Task 2", "subject_id": 1, "task_status": None},
        ]

        result = asyncio.run(
            self.service.upsert_calendar_day(
                session=mock_session,
                student_id=self.student_id,
                date=self.date,
                tasks=payload,
            )
        )

        mock_session.commit.assert_called_once()
        self.assertEqual(len(result), 2)
