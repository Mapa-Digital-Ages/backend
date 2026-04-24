"""Tests for the student service."""

import asyncio
import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import IntegrityError

import tests.keys_test  # noqa: F401
from md_backend.services.student_service import StudentService


class TestStudentService(unittest.TestCase):
    def setUp(self):
        self.service = StudentService()
        self.valid_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "password": "securepass123",
            "birth_date": datetime.date(2010, 5, 20),
            "student_class": "5A",
        }

    def test_create_student_success(self):
        mock_session = AsyncMock()
        mock_session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.flush = AsyncMock()

        result = asyncio.run(self.service.create_student(**self.valid_data, session=mock_session))

        self.assertIsNotNone(result)
        self.assertEqual(result["first_name"], "John")
        self.assertEqual(result["last_name"], "Doe")
        self.assertEqual(result["email"], "john@example.com")
        self.assertEqual(result["student_class"], "5A")
        self.assertNotIn("password", result)

    def test_create_student_integrity_error_returns_none(self):
        mock_session = AsyncMock()
        mock_session.flush.side_effect = IntegrityError("", "", Exception())

        result = asyncio.run(self.service.create_student(**self.valid_data, session=mock_session))

        self.assertIsNone(result)
        mock_session.rollback.assert_called_once()

class TestStudentServiceGet(unittest.TestCase):
    """Unit tests para get_students e get_student_by_id."""

    def setUp(self):
        self.service = StudentService()

    def test_to_dict_excludes_password(self):
        """Valida que _to_dict nunca inclui senha."""
        user = MagicMock()
        user.id = 1
        user.first_name = "John"
        user.last_name = "Doe"
        user.email = "john@example.com"
        user.phone_number = ""
        user.birth_date = datetime.date(2010, 5, 20)
        user.is_active = True
        user.created_at = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

        student = MagicMock()
        student.id = 1
        student.student_class = "5A"
        student.school_id = None

        result = self.service._to_dict(user, student)

        self.assertNotIn("password", result)
        self.assertNotIn("hashed_password", result)
        self.assertEqual(result["email"], "john@example.com")
        self.assertEqual(result["school_id"], "")

    def test_update_student_returns_none_for_missing_id(self):
        """Valida que update_student retorna None para ID inexistente."""
        import asyncio
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            self.service.update_student(
                session=mock_session,
                student_id=99999,
                data={"first_name": "Jane"},
            )
        )
        self.assertIsNone(result)