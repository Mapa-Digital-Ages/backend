"""Tests for the admin service."""

import asyncio
import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

import tests.keys_test  # noqa: F401
from md_backend.models.db_models import (
    GuardianStatusEnum,
    PartnershipStatusEnum,
    SchoolCompanyPartnership,
    SponsorshipRequest,
    SponsorshipRequestStatusEnum,
)
from md_backend.services.admin_service import AdminService


def _make_user(
    *,
    user_id=None,
    email="user@test.com",
    first_name="First",
    last_name="Last",
    guardian_status=GuardianStatusEnum.WAITING,
    has_guardian=True,
    has_student=False,
    has_admin=False,
    has_company=False,
    is_superadmin=False,
    created_at=None,
):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = email
    user.first_name = first_name
    user.last_name = last_name
    user.created_at = created_at or datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

    if has_guardian:
        guardian = MagicMock()
        guardian.guardian_status = guardian_status
        user.guardian_profile = guardian
    else:
        user.guardian_profile = None

    if has_student:
        user.student_profile = MagicMock()
    else:
        user.student_profile = None

    if has_admin:
        admin = MagicMock()
        admin.is_superadmin = is_superadmin
        user.admin_profile = admin
    else:
        user.admin_profile = None

    if has_company:
        user.company_profile = MagicMock()
    else:
        user.company_profile = None
    return user


def _session_with_users(users):
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = users
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    return mock_session


def _session_with_user(user):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    return mock_session


class TestAdminServiceListUsers(unittest.TestCase):
    def test_list_users_returns_serialized_guardian(self):
        service = AdminService()
        user = _make_user(email="a@test.com", guardian_status=GuardianStatusEnum.WAITING)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["email"], "a@test.com")
        self.assertEqual(result[0]["status"], "waiting")
        self.assertEqual(result[0]["role"], "guardian")
        self.assertFalse(result[0]["is_superadmin"])

    def test_list_users_serializes_admin_role(self):
        service = AdminService()
        user = _make_user(
            email="admin@test.com",
            has_guardian=False,
            has_admin=True,
            is_superadmin=True,
        )
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session))

        self.assertEqual(result[0]["role"], "admin")
        self.assertEqual(result[0]["status"], "approved")
        self.assertTrue(result[0]["is_superadmin"])

    def test_list_users_serializes_student_role(self):
        service = AdminService()
        user = _make_user(
            email="student@test.com",
            has_guardian=False,
            has_student=True,
        )
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session))

        self.assertEqual(result[0]["role"], "student")
        self.assertEqual(result[0]["status"], "approved")

    def test_list_users_serializes_company_role(self):
        service = AdminService()
        user = _make_user(
            email="company@test.com",
            has_guardian=False,
            has_company=True,
        )
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session))

        self.assertEqual(result[0]["role"], "company")
        self.assertEqual(result[0]["status"], "approved")

    def test_list_users_status_approved_mapping(self):
        service = AdminService()
        user = _make_user(guardian_status=GuardianStatusEnum.APPROVED)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session))
        self.assertEqual(result[0]["status"], "approved")

    def test_list_users_status_rejected_mapping(self):
        service = AdminService()
        user = _make_user(guardian_status=GuardianStatusEnum.REJECTED)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session))
        self.assertEqual(result[0]["status"], "rejected")

    def test_list_users_filter_status_waiting(self):
        service = AdminService()
        user = _make_user(guardian_status=GuardianStatusEnum.WAITING)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session, status_filter="waiting"))

        self.assertEqual(len(result), 1)
        session.execute.assert_called_once()

    def test_list_users_filter_role_guardian(self):
        service = AdminService()
        user = _make_user()
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session, role="guardian"))

        self.assertEqual(len(result), 1)

    def test_list_users_filter_role_student(self):
        service = AdminService()
        user = _make_user(has_guardian=False, has_student=True)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session, role="student"))

        self.assertEqual(len(result), 1)

    def test_list_users_filter_role_admin(self):
        service = AdminService()
        user = _make_user(has_guardian=False, has_admin=True, is_superadmin=True)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session, role="admin"))

        self.assertEqual(len(result), 1)

    def test_list_users_filter_role_company(self):
        service = AdminService()
        user = _make_user(has_guardian=False, has_company=True)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session, role="company"))

        self.assertEqual(len(result), 1)


class TestAdminServiceUpdateStatus(unittest.TestCase):
    def test_update_status_approved(self):
        service = AdminService()
        user = _make_user(guardian_status=GuardianStatusEnum.WAITING)
        session = _session_with_user(user)

        result = asyncio.run(service.update_user_status(session, user.id, "approved"))

        assert result is not None
        self.assertNotIn("error", result)
        self.assertEqual(user.guardian_profile.guardian_status, GuardianStatusEnum.APPROVED)
        session.commit.assert_called_once()

    def test_update_status_user_not_found(self):
        service = AdminService()
        session = _session_with_user(None)

        result = asyncio.run(service.update_user_status(session, uuid.uuid4(), "approved"))

        self.assertIsNone(result)
        session.commit.assert_not_called()

    def test_update_status_superadmin_protected(self):
        service = AdminService()
        user = _make_user(
            has_guardian=False,
            has_admin=True,
            is_superadmin=True,
        )
        session = _session_with_user(user)

        result = asyncio.run(service.update_user_status(session, user.id, "rejected"))

        assert result is not None
        self.assertIn("error", result)
        session.commit.assert_not_called()

    def test_update_status_user_without_guardian_profile(self):
        service = AdminService()
        user = _make_user(has_guardian=False, has_student=True)
        session = _session_with_user(user)

        result = asyncio.run(service.update_user_status(session, user.id, "approved"))

        assert result is not None
        self.assertIn("error", result)
        session.commit.assert_not_called()


def _make_partnership(granted_spots: int = 5):
    p = MagicMock(spec=SchoolCompanyPartnership)
    p.id = uuid.uuid4()
    p.school_id = uuid.uuid4()
    p.company_id = uuid.uuid4()
    p.request_id = uuid.uuid4()
    p.granted_spots = granted_spots
    p.status = PartnershipStatusEnum.PENDING
    p.created_at = MagicMock()
    p.created_at.isoformat.return_value = "2024-01-01T00:00:00"
    return p


def _make_sponsorship(remaining_spots: int, requested_spots: int = 10):
    s = MagicMock(spec=SponsorshipRequest)
    s.id = uuid.uuid4()
    s.remaining_spots = remaining_spots
    s.requested_spots = requested_spots
    s.status = SponsorshipRequestStatusEnum.PARTIALLY_FULFILLED
    return s


def _session_with_partnership(partnership, sponsorship):
    session = AsyncMock()

    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested_cm)

    partnership_result = MagicMock()
    partnership_result.scalar_one_or_none.return_value = partnership

    sponsorship_result = MagicMock()
    sponsorship_result.scalar_one_or_none.return_value = sponsorship

    session.execute = AsyncMock(side_effect=[partnership_result, sponsorship_result])
    return session


class TestAdminServicePartnershipStatus(unittest.TestCase):
    def test_approve_sets_fulfilled_when_no_remaining_spots(self):
        """Aprovação com remaining_spots == 0 define request como FULFILLED."""
        partnership = _make_partnership(granted_spots=10)
        sponsorship = _make_sponsorship(remaining_spots=0, requested_spots=10)
        session = _session_with_partnership(partnership, sponsorship)

        asyncio.run(AdminService().update_partnership_status(session, partnership.id, "APPROVED"))

        self.assertEqual(partnership.status, PartnershipStatusEnum.APPROVED)
        self.assertEqual(sponsorship.status, SponsorshipRequestStatusEnum.FULFILLED)

    def test_approve_sets_partially_fulfilled_when_spots_remain(self):
        """Aprovação com remaining_spots > 0 define request como PARTIALLY_FULFILLED."""
        partnership = _make_partnership(granted_spots=3)
        sponsorship = _make_sponsorship(remaining_spots=7, requested_spots=10)
        session = _session_with_partnership(partnership, sponsorship)

        asyncio.run(AdminService().update_partnership_status(session, partnership.id, "APPROVED"))

        self.assertEqual(partnership.status, PartnershipStatusEnum.APPROVED)
        self.assertEqual(sponsorship.status, SponsorshipRequestStatusEnum.PARTIALLY_FULFILLED)

    def test_reject_returns_spots_to_remaining(self):
        """Rejeição devolve granted_spots ao remaining_spots da request."""
        partnership = _make_partnership(granted_spots=5)
        sponsorship = _make_sponsorship(remaining_spots=2, requested_spots=10)
        session = _session_with_partnership(partnership, sponsorship)

        asyncio.run(AdminService().update_partnership_status(session, partnership.id, "REJECTED"))

        self.assertEqual(sponsorship.remaining_spots, 7)
        self.assertEqual(partnership.status, PartnershipStatusEnum.REJECTED)

    def test_reject_sets_open_when_all_spots_returned(self):
        """Rejeição que restaura todas as vagas define request como OPEN."""
        partnership = _make_partnership(granted_spots=10)
        sponsorship = _make_sponsorship(remaining_spots=0, requested_spots=10)
        session = _session_with_partnership(partnership, sponsorship)

        asyncio.run(AdminService().update_partnership_status(session, partnership.id, "REJECTED"))

        self.assertEqual(sponsorship.remaining_spots, 10)
        self.assertEqual(sponsorship.status, SponsorshipRequestStatusEnum.OPEN)

    def test_reject_sets_partially_fulfilled_when_spots_partially_returned(self):
        """Rejeição parcial mantém request como PARTIALLY_FULFILLED."""
        partnership = _make_partnership(granted_spots=3)
        sponsorship = _make_sponsorship(remaining_spots=0, requested_spots=10)
        session = _session_with_partnership(partnership, sponsorship)

        asyncio.run(AdminService().update_partnership_status(session, partnership.id, "REJECTED"))

        self.assertEqual(sponsorship.remaining_spots, 3)
        self.assertEqual(sponsorship.status, SponsorshipRequestStatusEnum.PARTIALLY_FULFILLED)

    def test_returns_none_when_partnership_not_found(self):
        """Retorna None quando a parceria não existe."""
        session = AsyncMock()

        nested_cm = MagicMock()
        nested_cm.__aenter__ = AsyncMock(return_value=None)
        nested_cm.__aexit__ = AsyncMock(return_value=False)
        session.begin_nested = MagicMock(return_value=nested_cm)

        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=not_found)

        result = asyncio.run(
            AdminService().update_partnership_status(session, uuid.uuid4(), "APPROVED")
        )

        self.assertIsNone(result)
