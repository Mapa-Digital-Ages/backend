"""Unit tests for password_reset_service edge branches."""

import asyncio
import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

import tests.keys_test  # noqa: F401
from md_backend.services.password_reset_service import (
    PasswordResetService,
    _ensure_aware_utc,
)


class TestEnsureAwareUtc(unittest.TestCase):
    """Cover _ensure_aware_utc tz-aware branch."""

    def test_naive_datetime_is_treated_as_utc(self):
        naive = datetime.datetime(2024, 1, 2, 3, 4, 5)
        result = _ensure_aware_utc(naive)
        self.assertEqual(result.tzinfo, datetime.UTC)
        self.assertEqual(result.year, 2024)

    def test_aware_datetime_is_converted_to_utc(self):
        # tz-aware non-UTC value triggers the astimezone(UTC) branch.
        eastern = datetime.timezone(datetime.timedelta(hours=-5))
        aware = datetime.datetime(2024, 1, 2, 8, 0, 0, tzinfo=eastern)

        result = _ensure_aware_utc(aware)

        self.assertEqual(result.tzinfo, datetime.UTC)
        self.assertEqual(result.hour, 13)


class TestConfirmResetUnknownEmail(unittest.TestCase):
    """Cover confirm_reset → user is None → return False."""

    def test_returns_false_when_user_missing(self):
        service = PasswordResetService()

        no_user_result = MagicMock()
        no_user_result.scalar_one_or_none.return_value = None
        mock_session = AsyncMock()
        mock_session.execute.return_value = no_user_result

        result = asyncio.run(
            service.confirm_reset(
                email="ghost@example.com",
                code="123456",
                new_password="newpass1234",
                session=mock_session,
            )
        )
        self.assertFalse(result)


class TestGetValidResetEntryExpiredSkipped(unittest.TestCase):
    """Cover the `expires_at <= now` continue branch."""

    def test_expired_entries_are_skipped(self):
        service = PasswordResetService()

        expired_entry = MagicMock()
        expired_entry.expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        expired_entry.code_hash = "irrelevant"

        scalars_result = MagicMock()
        scalars_result.scalars.return_value = iter([expired_entry])
        mock_session = AsyncMock()
        mock_session.execute.return_value = scalars_result

        result = asyncio.run(
            service._get_valid_reset_entry(
                user_id=uuid.uuid4(),
                code="123456",
                session=mock_session,
            )
        )
        self.assertIsNone(result)
