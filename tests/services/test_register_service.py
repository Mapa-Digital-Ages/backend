"""Tests for the register service."""

import asyncio
import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import IntegrityError

import tests.keys_test  # noqa: F401
from md_backend.models.db_models import ClassEnum
from md_backend.services.register_service import RegisterService


def _guardian_kwargs(**overrides):
    base = {
        "email": "race@test.com",
        "password": "validpass123",
        "first_name": "Race",
        "last_name": "User",
    }
    base.update(overrides)
    return base


def _student_kwargs(**overrides):
    base = {
        "email": "race_student@test.com",
        "password": "validpass123",
        "first_name": "Race",
        "last_name": "Student",
        "birth_date": datetime.date(2010, 5, 1),
        "student_class": ClassEnum.CLASS_5TH,
    }
    base.update(overrides)
    return base


class TestRegisterServiceIntegrityError(unittest.TestCase):
    def test_register_guardian_returns_none_on_integrity_error(self):
        service = RegisterService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()
        mock_session.commit.side_effect = IntegrityError("", "", Exception())

        result = asyncio.run(
            service.register_guardian(**_guardian_kwargs(), session=mock_session)
        )

        self.assertIsNone(result)
        mock_session.rollback.assert_called_once()

    def test_register_student_returns_none_on_integrity_error(self):
        service = RegisterService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()
        mock_session.commit.side_effect = IntegrityError("", "", Exception())

        result = asyncio.run(
            service.register_student(**_student_kwargs(), session=mock_session)
        )

        self.assertIsNone(result)
        mock_session.rollback.assert_called_once()


class TestRegisterServiceDuplicateEmail(unittest.TestCase):
    def test_register_guardian_returns_none_when_email_exists(self):
        service = RegisterService()

        existing_user = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()

        result = asyncio.run(
            service.register_guardian(
                **_guardian_kwargs(email="dup@test.com"), session=mock_session
            )
        )

        self.assertIsNone(result)
        mock_session.add.assert_not_called()

    def test_register_student_returns_none_when_email_exists(self):
        service = RegisterService()

        existing_user = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()

        result = asyncio.run(
            service.register_student(
                **_student_kwargs(email="dup_student@test.com"), session=mock_session
            )
        )

        self.assertIsNone(result)
        mock_session.add.assert_not_called()


class TestRegisterServiceSuccess(unittest.TestCase):
    def test_register_guardian_success(self):
        service = RegisterService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()

        result = asyncio.run(
            service.register_guardian(
                **_guardian_kwargs(email="ok@test.com"), session=mock_session
            )
        )

        assert result is not None
        self.assertEqual(result["detail"], "Registration completed. Awaiting approval.")
        self.assertIn("id", result)
        mock_session.commit.assert_called_once()

    def test_register_guardian_success_with_phone_number(self):
        service = RegisterService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        added: list = []
        mock_session.add = MagicMock(side_effect=lambda obj: added.append(obj))

        result = asyncio.run(
            service.register_guardian(
                **_guardian_kwargs(email="phone@test.com"),
                phone_number="+5511000000000",
                session=mock_session,
            )
        )

        assert result is not None
        user = next(o for o in added if hasattr(o, "phone_number"))
        self.assertEqual(user.phone_number, "+5511000000000")

    def test_register_student_success(self):
        service = RegisterService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()

        result = asyncio.run(
            service.register_student(
                **_student_kwargs(email="stu@test.com"), session=mock_session
            )
        )

        assert result is not None
        self.assertEqual(result["detail"], "Registration completed.")
        self.assertIn("id", result)
        mock_session.commit.assert_called_once()

    def test_register_student_success_with_phone_and_school(self):
        service = RegisterService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        added: list = []
        mock_session.add = MagicMock(side_effect=lambda obj: added.append(obj))

        school_id = uuid.uuid4()
        result = asyncio.run(
            service.register_student(
                **_student_kwargs(email="stu_full@test.com"),
                phone_number="+5511000000001",
                school_id=school_id,
                session=mock_session,
            )
        )

        assert result is not None
        user = next(o for o in added if hasattr(o, "phone_number"))
        student = next(o for o in added if hasattr(o, "school_id"))
        self.assertEqual(user.phone_number, "+5511000000001")
        self.assertEqual(student.school_id, school_id)
