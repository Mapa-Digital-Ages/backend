"""Tests for the setup service."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

import tests.keys_test  # noqa: F401
from md_backend.services.setup_service import SetupService


def _superadmin_kwargs(**overrides):
    base = {
        "email": "admin@test.com",
        "password": "adminpass123",
        "first_name": "Super",
        "last_name": "Admin",
    }
    base.update(overrides)
    return base


class TestSetupService(unittest.TestCase):
    def test_create_superadmin_success(self):
        service = SetupService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()

        result = asyncio.run(
            service.create_superadmin(**_superadmin_kwargs(), session=mock_session)
        )

        assert result is not None
        self.assertEqual(result["detail"], "Superadmin created successfully")
        self.assertIn("id", result)
        self.assertEqual(mock_session.add.call_count, 2)
        mock_session.commit.assert_called_once()

    def test_create_superadmin_persists_phone_number(self):
        service = SetupService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        added: list = []
        mock_session.add = MagicMock(side_effect=lambda obj: added.append(obj))

        result = asyncio.run(
            service.create_superadmin(
                **_superadmin_kwargs(),
                phone_number="+5511000000000",
                session=mock_session,
            )
        )

        assert result is not None
        user = next(o for o in added if hasattr(o, "phone_number"))
        self.assertEqual(user.phone_number, "+5511000000000")
        self.assertEqual(user.first_name, "Super")
        self.assertEqual(user.last_name, "Admin")

    def test_create_superadmin_without_phone_number(self):
        service = SetupService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        added: list = []
        mock_session.add = MagicMock(side_effect=lambda obj: added.append(obj))

        result = asyncio.run(
            service.create_superadmin(**_superadmin_kwargs(), session=mock_session)
        )

        assert result is not None
        user = next(o for o in added if hasattr(o, "phone_number"))
        self.assertIsNone(user.phone_number)

    def test_create_superadmin_already_exists(self):
        service = SetupService()

        existing_admin = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_admin

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()

        result = asyncio.run(
            service.create_superadmin(
                **_superadmin_kwargs(email="admin2@test.com"), session=mock_session
            )
        )

        self.assertIsNone(result)
        mock_session.add.assert_not_called()
