"""Unit tests for StudentService."""

import asyncio
import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import IntegrityError

import tests.keys_test  # noqa: F401
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

        result = asyncio.run(
            self.service.create_student(**self.kwargs, session=mock_session)
        )

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

        result = asyncio.run(
            self.service.create_student(**self.kwargs, session=mock_session)
        )

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
