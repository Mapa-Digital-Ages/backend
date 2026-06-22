"""Unit tests for password_reset_service edge branches."""

import asyncio
import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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

    def test_non_expiring_entry_remains_valid_until_consumed(self):
        service = PasswordResetService()
        reset_entry = MagicMock()
        reset_entry.expires_at = None
        reset_entry.code_hash = "hashed-code"
        scalars_result = MagicMock()
        scalars_result.scalars.return_value = iter([reset_entry])
        session = AsyncMock()
        session.execute.return_value = scalars_result

        with patch(
            "md_backend.services.password_reset_service.verify_password",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = asyncio.run(
                service._get_valid_reset_entry(
                    user_id=uuid.uuid4(),
                    code="123456",
                    session=session,
                )
            )

        self.assertIs(result, reset_entry)


class TestRequestResetEmailDispatch(unittest.TestCase):
    """Cover the email dispatch wiring in request_reset."""

    def _build_session_with_user(self, user):
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user
        session = AsyncMock()
        session.execute.return_value = user_result
        # session.add is synchronous in real SQLAlchemy; override the AsyncMock default.
        session.add = MagicMock()
        return session

    def test_sender_is_called_with_generated_code(self):
        sender = AsyncMock()
        service = PasswordResetService(email_sender=sender)

        user = MagicMock()
        user.id = uuid.uuid4()
        session = self._build_session_with_user(user)

        with patch(
            "md_backend.services.password_reset_service._generate_reset_code",
            return_value="424242",
        ):
            asyncio.run(service.request_reset(email="user@test.com", session=session))

        sender.send_password_reset.assert_awaited_once_with(to_email="user@test.com", code="424242")

    def test_service_propagates_sender_exceptions(self):
        # The service does not catch sender errors; the EmailSender itself swallows
        # SMTP failures (see test_email_sender). This test pins that contract so the
        # safety net stays in EmailSender, not silently in the service.
        sender = AsyncMock()
        sender.send_password_reset.side_effect = RuntimeError("smtp boom")
        service = PasswordResetService(email_sender=sender)

        user = MagicMock()
        user.id = uuid.uuid4()
        session = self._build_session_with_user(user)

        with self.assertRaises(RuntimeError):
            asyncio.run(service.request_reset(email="user@test.com", session=session))

    def test_sender_not_called_for_unknown_email(self):
        sender = AsyncMock()
        service = PasswordResetService(email_sender=sender)

        session = self._build_session_with_user(user=None)

        asyncio.run(service.request_reset(email="ghost@test.com", session=session))

        sender.send_password_reset.assert_not_awaited()


class TestInitialPasswordSetup(unittest.TestCase):
    def test_prepares_code_without_committing_the_batch_transaction(self):
        service = PasswordResetService()
        session = AsyncMock()
        session.add = MagicMock()
        user_id = uuid.uuid4()

        with (
            patch(
                "md_backend.services.password_reset_service._generate_reset_code",
                return_value="135790",
            ),
            patch(
                "md_backend.services.password_reset_service.hash_password",
                new_callable=AsyncMock,
                return_value="hashed-code",
            ),
        ):
            code = asyncio.run(
                service.prepare_initial_password_setup(user_id=user_id, session=session)
            )

        self.assertEqual(code, "135790")
        reset_entry = session.add.call_args.args[0]
        self.assertEqual(reset_entry.user_id, user_id)
        self.assertEqual(reset_entry.code_hash, "hashed-code")
        self.assertIsNone(reset_entry.expires_at)
        session.commit.assert_not_awaited()

    def test_dispatch_uses_background_tasks_when_available(self):
        sender = AsyncMock()
        service = PasswordResetService(email_sender=sender)
        background_tasks = MagicMock()

        asyncio.run(
            service.dispatch_reset_email(
                email="new.user@example.com",
                code="246802",
                background_tasks=background_tasks,
            )
        )

        background_tasks.add_task.assert_called_once_with(
            sender.send_password_reset,
            to_email="new.user@example.com",
            code="246802",
        )
        sender.send_password_reset.assert_not_awaited()

    def test_initial_setup_email_is_marked_as_non_expiring(self):
        sender = AsyncMock()
        service = PasswordResetService(email_sender=sender)

        asyncio.run(
            service.dispatch_initial_password_setup_email(
                email="new.user@example.com",
                code="975310",
            )
        )

        sender.send_initial_password_setup.assert_awaited_once_with(
            to_email="new.user@example.com",
            code="975310",
        )

    def test_initial_setup_email_uses_batch_link_sender_in_background(self):
        sender = AsyncMock()
        service = PasswordResetService(email_sender=sender)
        background_tasks = MagicMock()

        asyncio.run(
            service.dispatch_initial_password_setup_email(
                email="batch.user@example.com",
                code="864209",
                background_tasks=background_tasks,
            )
        )

        background_tasks.add_task.assert_called_once_with(
            sender.send_initial_password_setup,
            to_email="batch.user@example.com",
            code="864209",
        )
        sender.send_password_reset.assert_not_awaited()
