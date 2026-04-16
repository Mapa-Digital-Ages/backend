"""Tests for the admin service."""

import asyncio
import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock

import tests.keys_test  # noqa: F401
from md_backend.models.db_models import UserStatus
from md_backend.services.admin_service import AdminService


def _make_mock_user(
    id=1,
    email="user@test.com",
    status=UserStatus.AGUARDANDO,
    is_superadmin=False,
    created_at=None,
):
    user = MagicMock()
    user.id = id
    user.email = email
    user.status = status
    user.is_superadmin = is_superadmin
    user.created_at = created_at or datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return user


class TestAdminServiceListUsers(unittest.TestCase):
    def test_list_users_returns_all(self):
        service = AdminService()

        users = [
            _make_mock_user(id=1, email="a@test.com"),
            _make_mock_user(id=2, email="b@test.com", status=UserStatus.APROVADO),
        ]

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = users
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(service.list_users(mock_session))

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["email"], "a@test.com")
        self.assertEqual(result[1]["status"], "aprovado")

    def test_list_users_with_filter(self):
        service = AdminService()

        users = [_make_mock_user(id=1, email="a@test.com", status=UserStatus.AGUARDANDO)]

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = users
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(service.list_users(mock_session, status_filter=UserStatus.AGUARDANDO))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "aguardando")


class TestAdminServiceUpdateStatus(unittest.TestCase):
    def test_update_status_success(self):
        service = AdminService()

        user = _make_mock_user(id=1, email="user@test.com", status=UserStatus.AGUARDANDO)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            service.update_user_status(mock_session, "user@test.com", UserStatus.APROVADO)
        )

        self.assertIsNotNone(result)
        self.assertNotIn("error", result)
        self.assertEqual(user.status, UserStatus.APROVADO)
        mock_session.commit.assert_called_once()

    def test_update_status_user_not_found(self):
        service = AdminService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            service.update_user_status(mock_session, "ghost@test.com", UserStatus.APROVADO)
        )

        self.assertIsNone(result)

    def test_update_status_superadmin_protection(self):
        service = AdminService()

        user = _make_mock_user(id=1, is_superadmin=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            service.update_user_status(mock_session, "user@test.com", UserStatus.NEGADO)
        )

        self.assertIn("error", result)
        mock_session.commit.assert_not_called()
