"""Unit tests for GuardianService edge branches."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import IntegrityError

import tests.keys_test  # noqa: F401
from md_backend.services.guardian_service import GuardianService


class TestCreateGuardianIntegrityError(unittest.TestCase):
    """Cover the IntegrityError → rollback branch in create_guardian."""

    def test_returns_none_and_rolls_back_on_integrity_error(self):
        service = GuardianService()

        no_user_result = MagicMock()
        no_user_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = no_user_result
        mock_session.add = MagicMock()
        mock_session.commit.side_effect = IntegrityError("forced", {}, Exception("forced"))

        result = asyncio.run(
            service.create_guardian(
                first_name="A",
                last_name="B",
                email="dup@example.com",
                password="pass12345",
                session=mock_session,
            )
        )
        self.assertIsNone(result)
        mock_session.rollback.assert_awaited_once()


class TestUpdateGuardianBranches(unittest.TestCase):
    """Cover the None-value skip and commit-failure branches in update_guardian."""

    def _profiles_with_active_student(self):
        user_profile = MagicMock()
        user_profile.email = "current@example.com"
        user_profile.first_name = "Cur"
        user_profile.last_name = "Rent"
        user_profile.phone_number = "+550000"
        user_profile.is_active = True
        user_profile.created_at = None
        user_profile.deactivated_at = None

        guardian_profile = MagicMock()
        guardian_profile.user_id = uuid.uuid4()
        guardian_status = MagicMock()
        guardian_status.value = "approved"
        guardian_profile.guardian_status = guardian_status

        active_student = MagicMock()
        active_student.deactivated_at = None
        active_student.user_id = uuid.uuid4()
        active_student.user.first_name = "S"
        active_student.user.last_name = "T"
        active_student.user.email = "s@t.com"
        active_student.birth_date = None
        student_class = MagicMock()
        student_class.value = "5th class"
        active_student.student_class = student_class

        deactivated_student = MagicMock()
        deactivated_student.deactivated_at = MagicMock()  # truthy → skipped

        guardian_profile.students = [active_student, deactivated_student]
        return user_profile, guardian_profile

    def test_skips_none_values_and_returns_dict_with_active_students(self):
        service = GuardianService()
        user_profile, guardian_profile = self._profiles_with_active_student()

        row_result = MagicMock()
        row_result.one_or_none.return_value = (user_profile, guardian_profile)

        mock_session = AsyncMock()
        mock_session.execute.return_value = row_result

        result = asyncio.run(
            service.update_guardian(
                session=mock_session,
                guardian_id=uuid.uuid4(),
                data={"first_name": "Updated", "phone_number": None},
            )
        )

        assert isinstance(result, dict)
        self.assertEqual(user_profile.first_name, "Updated")
        # phone_number was None → must remain unchanged
        self.assertEqual(user_profile.phone_number, "+550000")
        # Only active student is included.
        self.assertEqual(len(result["students"]), 1)
        self.assertEqual(result["students"][0]["first_name"], "S")

    def test_commit_failure_rolls_back_and_reraises(self):
        service = GuardianService()
        user_profile, guardian_profile = self._profiles_with_active_student()

        row_result = MagicMock()
        row_result.one_or_none.return_value = (user_profile, guardian_profile)

        mock_session = AsyncMock()
        mock_session.execute.return_value = row_result
        mock_session.commit.side_effect = RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            asyncio.run(
                service.update_guardian(
                    session=mock_session,
                    guardian_id=uuid.uuid4(),
                    data={"first_name": "X"},
                )
            )
        mock_session.rollback.assert_awaited_once()


class TestGetGuardiansListBranches(unittest.TestCase):
    """Cover the active-student append branch inside get_guardians."""

    def test_list_includes_active_student_dict(self):
        service = GuardianService()

        user_profile = MagicMock()
        user_profile.email = "g@example.com"
        user_profile.first_name = "G"
        user_profile.last_name = "X"
        user_profile.phone_number = None
        user_profile.is_active = True
        user_profile.created_at = None
        user_profile.deactivated_at = None

        guardian_profile = MagicMock()
        guardian_profile.user_id = uuid.uuid4()
        gstatus = MagicMock()
        gstatus.value = "approved"
        guardian_profile.guardian_status = gstatus

        active_student = MagicMock()
        active_student.deactivated_at = None
        active_student.user_id = uuid.uuid4()
        active_student.user.first_name = "A"
        active_student.user.last_name = "B"
        active_student.user.email = "a@b.com"
        active_student.birth_date = None
        sclass = MagicMock()
        sclass.value = "5th class"
        active_student.student_class = sclass

        deactivated_student = MagicMock()
        deactivated_student.deactivated_at = MagicMock()  # truthy → skipped

        guardian_profile.students = [active_student, deactivated_student]

        # Sequence of session.execute results:
        # 1) main query (rows)
        # 2) count_query (scalar)
        rows_result = MagicMock()
        rows_result.all.return_value = [(user_profile, guardian_profile)]
        count_result = MagicMock()
        count_result.scalar.return_value = 1

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [count_result, rows_result]

        result = asyncio.run(service.get_guardians(session=mock_session))

        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(result["items"][0]["students"]), 1)
        self.assertEqual(result["items"][0]["students"][0]["email"], "a@b.com")


class TestLinkStudentToGuardianException(unittest.TestCase):
    """Cover the commit-failure rollback branch in link_student_to_guardian."""

    def test_returns_false_when_commit_raises(self):
        service = GuardianService()

        guardian_profile = MagicMock()
        student_profile = MagicMock()

        guardian_result = MagicMock()
        guardian_result.scalar_one_or_none.return_value = guardian_profile
        student_result = MagicMock()
        student_result.scalar_one_or_none.return_value = student_profile
        existing_link_result = MagicMock()
        existing_link_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            guardian_result,
            student_result,
            existing_link_result,
        ]
        mock_session.add = MagicMock()
        mock_session.commit.side_effect = RuntimeError("db failed")

        result = asyncio.run(
            service.link_student_to_guardian(
                session=mock_session,
                guardian_id=uuid.uuid4(),
                student_id=uuid.uuid4(),
            )
        )
        self.assertFalse(result)
        mock_session.rollback.assert_awaited_once()
