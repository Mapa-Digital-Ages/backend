"""Tests for the admin service."""

import asyncio
import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

import tests.keys_test  # noqa: F401
from md_backend.models.db_models import GuardianStatusEnum
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
    def test_list_users_returns_serialized_responsavel(self):
        service = AdminService()
        user = _make_user(email="a@test.com", guardian_status=GuardianStatusEnum.WAITING)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["email"], "a@test.com")
        self.assertEqual(result[0]["status"], "aguardando")
        self.assertEqual(result[0]["role"], "responsavel")
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
        self.assertEqual(result[0]["status"], "aprovado")
        self.assertTrue(result[0]["is_superadmin"])

    def test_list_users_serializes_aluno_role(self):
        service = AdminService()
        user = _make_user(
            email="aluno@test.com",
            has_guardian=False,
            has_student=True,
        )
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session))

        self.assertEqual(result[0]["role"], "aluno")
        self.assertEqual(result[0]["status"], "aprovado")

    def test_list_users_status_approved_mapping(self):
        service = AdminService()
        user = _make_user(guardian_status=GuardianStatusEnum.APPROVED)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session))
        self.assertEqual(result[0]["status"], "aprovado")

    def test_list_users_status_rejected_mapping(self):
        service = AdminService()
        user = _make_user(guardian_status=GuardianStatusEnum.REJECTED)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session))
        self.assertEqual(result[0]["status"], "negado")

    def test_list_users_filter_status_aguardando(self):
        service = AdminService()
        user = _make_user(guardian_status=GuardianStatusEnum.WAITING)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session, status_filter="aguardando"))

        self.assertEqual(len(result), 1)
        session.execute.assert_called_once()

    def test_list_users_filter_role_responsavel(self):
        service = AdminService()
        user = _make_user()
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session, role="responsavel"))

        self.assertEqual(len(result), 1)

    def test_list_users_filter_role_aluno(self):
        service = AdminService()
        user = _make_user(has_guardian=False, has_student=True)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session, role="aluno"))

        self.assertEqual(len(result), 1)

    def test_list_users_filter_role_admin(self):
        service = AdminService()
        user = _make_user(has_guardian=False, has_admin=True, is_superadmin=True)
        session = _session_with_users([user])

        result = asyncio.run(service.list_users(session, role="admin"))

        self.assertEqual(len(result), 1)


class TestAdminServiceUpdateStatus(unittest.TestCase):
    def test_update_status_approved(self):
        service = AdminService()
        user = _make_user(guardian_status=GuardianStatusEnum.WAITING)
        session = _session_with_user(user)

        result = asyncio.run(service.update_user_status(session, user.id, "aprovado"))

        self.assertIsNotNone(result)
        self.assertNotIn("error", result)
        self.assertEqual(user.guardian_profile.guardian_status, GuardianStatusEnum.APPROVED)
        session.commit.assert_called_once()

    def test_update_status_user_not_found(self):
        service = AdminService()
        session = _session_with_user(None)

        result = asyncio.run(service.update_user_status(session, uuid.uuid4(), "aprovado"))

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

        result = asyncio.run(service.update_user_status(session, user.id, "negado"))

        self.assertIn("error", result)
        session.commit.assert_not_called()

    def test_update_status_user_without_guardian_profile(self):
        service = AdminService()
        user = _make_user(has_guardian=False, has_student=True)
        session = _session_with_user(user)

        result = asyncio.run(service.update_user_status(session, user.id, "aprovado"))

        self.assertIn("error", result)
        session.commit.assert_not_called()
