"""Tests for the register service."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import IntegrityError

import tests.keys_test  # noqa: F401
from md_backend.services.register_service import RegisterService


class TestRegisterServiceIntegrityError(unittest.TestCase):
    def test_register_returns_none_on_integrity_error(self):
        """Test that concurrent duplicate registration is handled gracefully."""
        service = RegisterService()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()
        mock_session.commit.side_effect = IntegrityError("", "", Exception())

        result = asyncio.run(
            service.register("race@test.com", "validpass123", mock_session)
        )

        self.assertIsNone(result)
        mock_session.rollback.assert_called_once()
