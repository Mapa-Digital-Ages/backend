"""Tests for the setup service."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import tests.keys_test  # noqa: F401
from md_backend.services.setup_service import SetupService


class TestSetupService(unittest.TestCase):
    def test_create_superadmin_success(self):
        service = SetupService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()

        result = asyncio.run(
            service.create_superadmin("admin@test.com", "adminpass123", mock_session)
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["detail"], "Superadmin criado com sucesso")
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_create_superadmin_already_exists(self):
        service = SetupService()

        existing_admin = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_admin

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = asyncio.run(
            service.create_superadmin("admin2@test.com", "adminpass123", mock_session)
        )

        self.assertIsNone(result)
        mock_session.add.assert_not_called()
