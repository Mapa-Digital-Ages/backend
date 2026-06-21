"""Tests for the EmailSender used in password reset and other flows."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import tests.keys_test  # noqa: F401
from md_backend.utils.email_sender import EmailSender


class TestEmailSenderNoop(unittest.TestCase):
    """Without SMTP credentials, the sender logs and does not call aiosmtplib."""

    def _run_with_credentials(self, username: str, password: str) -> tuple:
        sender = EmailSender()
        with (
            patch("md_backend.utils.email_sender.settings") as mocked_settings,
            patch("md_backend.utils.email_sender.aiosmtplib.send") as mocked_send,
            patch("md_backend.utils.email_sender.logger") as mocked_logger,
        ):
            mocked_settings.SMTP_USERNAME = username
            mocked_settings.SMTP_PASSWORD = password
            asyncio.run(sender.send_password_reset(to_email="user@test.com", code="123456"))
        return mocked_send, mocked_logger

    def test_blank_credentials_skip_smtp_and_log_code(self):
        mocked_send, mocked_logger = self._run_with_credentials("", "")

        mocked_send.assert_not_called()
        mocked_logger.info.assert_called_once()
        args = mocked_logger.info.call_args.args
        self.assertIn("user@test.com", args)
        self.assertIn("123456", args)

    def test_partial_credentials_also_skip_smtp(self):
        # username without password (or vice-versa) is treated as misconfigured → noop.
        mocked_send, _ = self._run_with_credentials("user@example.com", "")
        mocked_send.assert_not_called()

        mocked_send, _ = self._run_with_credentials("", "secret")
        mocked_send.assert_not_called()


class TestEmailSenderSmtp(unittest.TestCase):
    """When SMTP credentials are present, the sender builds and sends a multipart email."""

    def _enabled_settings(self, mocked_settings):
        mocked_settings.SMTP_HOST = "smtp.example.com"
        mocked_settings.SMTP_PORT = 587
        mocked_settings.SMTP_USERNAME = "sender@example.com"
        mocked_settings.SMTP_PASSWORD = "app-password"
        mocked_settings.SMTP_FROM_NAME = "Mapa Digital"
        mocked_settings.FRONTEND_URL = "http://localhost:5173"

    def test_sends_message_with_reset_link_without_visible_code(self):
        sender = EmailSender()

        with (
            patch("md_backend.utils.email_sender.settings") as mocked_settings,
            patch(
                "md_backend.utils.email_sender.aiosmtplib.send", new_callable=AsyncMock
            ) as mocked_send,
        ):
            self._enabled_settings(mocked_settings)
            asyncio.run(sender.send_password_reset(to_email="dest@test.com", code="987654"))

        mocked_send.assert_awaited_once()
        message = mocked_send.await_args.args[0]
        kwargs = mocked_send.await_args.kwargs

        self.assertEqual(message["To"], "dest@test.com")
        self.assertEqual(message["Subject"], "Defina sua senha — Mapa Digital")
        self.assertIn("sender@example.com", message["From"])
        self.assertIn("Mapa Digital", message["From"])

        body_parts = [part.get_content() for part in message.iter_parts()]
        expected_url = "http://localhost:5173/forgot-password#email=dest%40test.com&code=987654"
        self.assertTrue(
            any(
                expected_url in part or expected_url.replace("&", "&amp;") in part
                for part in body_parts
            )
        )
        visible_text = "\n".join(body_parts).replace(expected_url, "")
        visible_text = visible_text.replace(expected_url.replace("&", "&amp;"), "")
        self.assertNotIn("Seu código", visible_text)
        self.assertNotIn("987654", visible_text)

        self.assertEqual(kwargs["hostname"], "smtp.example.com")
        self.assertEqual(kwargs["port"], 587)
        self.assertEqual(kwargs["username"], "sender@example.com")
        self.assertEqual(kwargs["password"], "app-password")
        self.assertTrue(kwargs["start_tls"])

    def test_smtp_failure_is_swallowed_and_logged(self):
        sender = EmailSender()

        with (
            patch("md_backend.utils.email_sender.settings") as mocked_settings,
            patch(
                "md_backend.utils.email_sender.aiosmtplib.send",
                new_callable=AsyncMock,
                side_effect=RuntimeError("connection refused"),
            ),
            patch("md_backend.utils.email_sender.logger") as mocked_logger,
        ):
            self._enabled_settings(mocked_settings)
            # Must not raise — endpoint must stay 200 to avoid email-enumeration leaks.
            asyncio.run(sender.send_password_reset(to_email="dest@test.com", code="000000"))

        mocked_logger.exception.assert_called_once()
        self.assertIn("dest@test.com", mocked_logger.exception.call_args.args)

    def test_non_expiring_setup_email_does_not_show_an_expiration_deadline(self):
        sender = EmailSender()

        with (
            patch("md_backend.utils.email_sender.settings") as mocked_settings,
            patch(
                "md_backend.utils.email_sender.aiosmtplib.send", new_callable=AsyncMock
            ) as mocked_send,
        ):
            self._enabled_settings(mocked_settings)
            asyncio.run(
                sender.send_password_reset(
                    to_email="dest@test.com",
                    code="123456",
                    expires_in_minutes=None,
                )
            )

        message = mocked_send.await_args.args[0]
        body = "\n".join(part.get_content() for part in message.iter_parts())
        self.assertIn("permanece válido até você definir sua senha", body)
        self.assertNotIn("expira em 15 minutos", body)

    def test_from_header_omits_display_name_when_blank(self):
        sender = EmailSender()

        with (
            patch("md_backend.utils.email_sender.settings") as mocked_settings,
            patch(
                "md_backend.utils.email_sender.aiosmtplib.send", new_callable=AsyncMock
            ) as mocked_send,
        ):
            self._enabled_settings(mocked_settings)
            mocked_settings.SMTP_FROM_NAME = ""
            asyncio.run(sender.send_password_reset(to_email="dest@test.com", code="111222"))

        message = mocked_send.await_args.args[0]
        self.assertEqual(message["From"], "sender@example.com")
