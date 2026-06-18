"""Unit tests for partnership support allocation helpers."""

import asyncio
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

import tests.keys_test  # noqa: F401
from md_backend.models.db_models import (
    PartnershipStatusEnum,
    PartnershipStudentSupport,
    SchoolCompanyPartnership,
    StudentProfile,
)
from md_backend.services.partnership_support_service import (
    sync_supported_students_for_school,
)


def _result_with_scalars(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _make_partnership(school_id):
    partnership = MagicMock(spec=SchoolCompanyPartnership)
    partnership.id = uuid.uuid4()
    partnership.school_id = school_id
    partnership.company_id = uuid.uuid4()
    partnership.granted_spots = 2
    partnership.status = PartnershipStatusEnum.APPROVED
    return partnership


class TestPartnershipSupportService(unittest.TestCase):
    def test_school_sync_fills_available_spot_for_approved_partnership(self):
        school_id = uuid.uuid4()
        partnership = _make_partnership(school_id)
        existing_student_id = uuid.uuid4()
        new_student_id = uuid.uuid4()

        existing_support = MagicMock(spec=PartnershipStudentSupport)
        existing_support.student_id = existing_student_id
        existing_support.is_active = True

        existing_student = MagicMock(spec=StudentProfile)
        existing_student.user_id = existing_student_id
        new_student = MagicMock(spec=StudentProfile)
        new_student.user_id = new_student_id

        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock(
            side_effect=[
                _result_with_scalars([partnership]),
                _result_with_scalars([existing_support]),
                _result_with_scalars([existing_student, new_student]),
            ]
        )

        asyncio.run(sync_supported_students_for_school(session, school_id))

        session.add.assert_called_once()
        added_support = session.add.call_args.args[0]
        self.assertIsInstance(added_support, PartnershipStudentSupport)
        self.assertEqual(added_support.partnership_id, partnership.id)
        self.assertEqual(added_support.school_id, school_id)
        self.assertEqual(added_support.company_id, partnership.company_id)
        self.assertEqual(added_support.student_id, new_student_id)
