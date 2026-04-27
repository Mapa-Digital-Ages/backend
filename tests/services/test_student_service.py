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
