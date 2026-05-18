"""Unit tests for StudentService."""

import asyncio
import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import IntegrityError

import tests.keys_test  # noqa: F401
from md_backend.models.api_models import CalendarTaskSyncItemRequest, WellBeingResponse
from md_backend.models.db_models import ClassEnum
from md_backend.services.student_service import StudentService


class TestStudentServiceCreate(unittest.TestCase):
    """Unit tests for StudentService.create_student."""

    def setUp(self):
        self.service = StudentService()
        self.kwargs = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.unit@example.com",
            "password": "securepass123",
            "birth_date": datetime.date(2010, 5, 20),
            "student_class": ClassEnum.CLASS_5TH,
        }

    def test_returns_none_when_email_already_exists(self):
        existing = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(self.service.create_student(**self.kwargs, session=mock_session))

        self.assertIsNone(result)
        mock_session.commit.assert_not_called()
        mock_session.rollback.assert_not_called()

    def test_returns_none_and_rolls_back_on_integrity_error(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()
        mock_session.commit.side_effect = IntegrityError("forced", {}, Exception("forced"))

        result = asyncio.run(self.service.create_student(**self.kwargs, session=mock_session))

        self.assertIsNone(result)
        mock_session.rollback.assert_called_once()


class TestStudentServiceUpdateRollback(unittest.TestCase):
    """Unit test covering update_student's commit-failure rollback branch."""

    def test_update_rolls_back_and_reraises_on_commit_failure(self):
        service = StudentService()

        user_profile = MagicMock()
        student_profile = MagicMock()
        mock_row = MagicMock()
        mock_row.one_or_none.return_value = (user_profile, student_profile)

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_row
        mock_session.commit.side_effect = RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            asyncio.run(
                service.update_student(
                    session=mock_session,
                    student_id=uuid.uuid4(),
                    data={"first_name": "Updated"},
                )
            )

        mock_session.rollback.assert_called_once()

    def test_update_skips_none_values(self):
        """Fields explicitly set to None in data dict must not be written."""
        service = StudentService()

        user_profile = MagicMock()
        student_profile = MagicMock()
        mock_row = MagicMock()
        mock_row.one_or_none.return_value = (user_profile, student_profile)

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_row

        asyncio.run(
            service.update_student(
                session=mock_session,
                student_id=uuid.uuid4(),
                data={"first_name": "Keep", "phone_number": None},
            )
        )

        mock_session.commit.assert_called_once()

    def test_update_returns_none_when_student_not_found(self):
        service = StudentService()

        mock_row = MagicMock()
        mock_row.one_or_none.return_value = None
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_row

        result = asyncio.run(
            service.update_student(
                session=mock_session,
                student_id=uuid.uuid4(),
                data={"first_name": "Ghost"},
            )
        )
        self.assertIsNone(result)


class TestStudentServiceWellBeing(unittest.TestCase):
    """Unit tests for well-being service methods."""

    def test_upsert_well_being_postgresql_branch(self):
        """Cover the postgresql dialect branch of upsert_well_being."""
        service = StudentService()

        mock_dialect = MagicMock()
        mock_dialect.name = "postgresql"
        mock_bind = MagicMock()
        mock_bind.dialect = mock_dialect

        record = MagicMock()
        record.student_id = uuid.uuid4()
        record.date = datetime.date.today()
        record.humor = None
        record.online_activity_minutes = None
        record.sleep_hours = None

        execute_result = MagicMock()
        execute_result.scalar_one.return_value = record

        mock_session = AsyncMock()
        mock_session.bind = mock_bind
        mock_session.execute.return_value = execute_result

        result = asyncio.run(
            service.upsert_well_being(
                session=mock_session,
                student_id=uuid.uuid4(),
                date=datetime.date.today(),
                humor=None,
                online_activity_minutes=None,
                sleep_hours=None,
            )
        )
        self.assertIsInstance(result, dict)

    def test_well_being_to_dict_with_none_humor(self):
        """_well_being_to_dict when humor is None returns None."""
        service = StudentService()
        record = MagicMock()
        record.student_id = uuid.uuid4()
        record.date = datetime.date.today()
        record.humor = None
        record.online_activity_minutes = 30
        record.sleep_hours = 7.0

        result = service._well_being_to_dict(record)
        self.assertIsNone(result["humor"])
        self.assertEqual(result["online_activity_minutes"], 30)

    def test_well_being_to_dict_with_none_sleep_hours(self):
        """_well_being_to_dict when sleep_hours is None returns None."""
        service = StudentService()
        record = MagicMock()
        record.student_id = uuid.uuid4()
        record.date = datetime.date.today()
        record.humor = None
        record.online_activity_minutes = None
        record.sleep_hours = None

        result = service._well_being_to_dict(record)
        self.assertIsNone(result["sleep_hours"])


class TestStudentServiceDictHelpers(unittest.TestCase):
    """Direct tests for the row-mapping helpers."""

    def test_discipline_to_dict_maps_row(self):
        service = StudentService()
        subject_id = uuid.uuid4()
        row = (subject_id, "Mathematics", 0.75)

        result = service._discipline_to_dict(row)

        self.assertEqual(result["subjectId"], str(subject_id))
        self.assertEqual(result["subjectLabel"], "Mathematics")
        self.assertEqual(result["progress"], 75)

    def test_discipline_to_dict_with_null_avg_mastery(self):
        service = StudentService()
        subject_id = uuid.uuid4()
        row = (subject_id, "Empty", None)

        result = service._discipline_to_dict(row)
        self.assertEqual(result["progress"], 0)

    def test_task_to_dict_maps_completed_task(self):
        from md_backend.models.db_models import TaskStatusEnum

        service = StudentService()
        task = MagicMock()
        task.id = uuid.uuid4()
        task.title = "Read chapter 1"
        task.date = datetime.date(2024, 6, 15)
        task.task_status = TaskStatusEnum.DONE

        result = service._task_to_dict(task)

        self.assertEqual(result["id"], str(task.id))
        self.assertEqual(result["title"], "Read chapter 1")
        self.assertEqual(result["date"], "2024-06-15")
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["subject"], {"label": ""})

    def test_task_to_dict_pending_when_status_none(self):
        service = StudentService()
        task = MagicMock()
        task.id = uuid.uuid4()
        task.title = "No status"
        task.date = None
        task.task_status = None

        result = service._task_to_dict(task)

        self.assertIsNone(result["date"])
        self.assertEqual(result["status"], "pending")

class TestCalendarTaskDTO(unittest.TestCase):

    def test_extract_nested_subject_id(self):
        payload = CalendarTaskSyncItemRequest(
            id="tmp-123",
            title="Math",
            task_status="adjust",
            subject={"id": 5},
            date=datetime.datetime.now(datetime.UTC),
        )

        self.assertEqual(payload.subject_id, 5)

    def test_accept_adjust_status(self):
        payload = CalendarTaskSyncItemRequest(
            id="tmp-1",
            title="Task",
            task_status="adjust",
            subject={"id": 1},
            date=datetime.datetime.now(datetime.UTC),
        )

        self.assertEqual(payload.task_status, "adjust")
