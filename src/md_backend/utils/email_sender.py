"""Email sender used by transactional flows (password reset, etc.)."""

import logging
from email.message import EmailMessage
from html import escape
from urllib.parse import urlencode

import aiosmtplib

from md_backend.utils.settings import settings

logger = logging.getLogger(__name__)

_PASSWORD_RESET_SUBJECT = "Código para redefinir sua senha — Mapa Digital"

_PASSWORD_RESET_TEXT = (
    "Olá,\n\n"
    "Use o código abaixo para redefinir a senha da sua conta no Mapa Digital:\n\n"
    "{code}\n\n"
    "O código expira em {expires_in_minutes} minutos. "
    "Se você não solicitou a redefinição, ignore esta mensagem."
)

_PASSWORD_RESET_HTML = (
    "<p>Olá,</p>"
    "<p>Use o código abaixo para redefinir a senha da sua conta no Mapa Digital:</p>"
    "<p><strong>{code}</strong></p>"
    "<p>O código expira em <strong>{expires_in_minutes} minutos</strong>. "
    "Se você não solicitou a redefinição, ignore esta mensagem.</p>"
)

_INITIAL_PASSWORD_SETUP_SUBJECT = "Defina sua senha — Mapa Digital"

_INITIAL_PASSWORD_SETUP_TEXT = (
    "Olá,\n\n"
    "Acesse o link abaixo para definir a senha da sua conta no Mapa Digital:\n\n"
    "{reset_url}\n\n"
    "O link permanece válido até você definir sua senha. "
    "Se você não esperava este email, ignore esta mensagem."
)

_INITIAL_PASSWORD_SETUP_HTML = (
    "<p>Olá,</p>"
    "<p>Acesse o link abaixo para definir a senha da sua conta no Mapa Digital.</p>"
    '<p><a href="{reset_url}">Definir minha senha</a></p>'
    "<p>O link permanece válido até você definir sua senha. "
    "Se você não esperava este email, ignore esta mensagem.</p>"
)


class EmailSender:
    """Send transactional emails via SMTP, with a safe no-op fallback for dev/tests."""

    async def send_password_reset(
        self,
        to_email: str,
        code: str,
        expires_in_minutes: int = 15,
    ) -> None:
        """Send the six-digit code used by the regular password-reset flow."""
        if not (settings.SMTP_USERNAME and settings.SMTP_PASSWORD):
            logger.info("[email noop] reset code for %s: %s", to_email, code)
            return

        message = EmailMessage()
        message["Subject"] = _PASSWORD_RESET_SUBJECT
        message["From"] = self._format_from()
        message["To"] = to_email

        message.set_content(
            _PASSWORD_RESET_TEXT.format(
                code=code,
                expires_in_minutes=expires_in_minutes,
            )
        )
        message.add_alternative(
            _PASSWORD_RESET_HTML.format(
                code=escape(code),
                expires_in_minutes=expires_in_minutes,
            ),
            subtype="html",
        )

        await self._send(message=message, to_email=to_email)

    async def send_initial_password_setup(self, to_email: str, code: str) -> None:
        """Send the non-expiring setup link used for users created in batch."""
        if not (settings.SMTP_USERNAME and settings.SMTP_PASSWORD):
            logger.info("[email noop] initial password setup code for %s: %s", to_email, code)
            return

        message = EmailMessage()
        message["Subject"] = _INITIAL_PASSWORD_SETUP_SUBJECT
        message["From"] = self._format_from()
        message["To"] = to_email
        reset_url = self._build_password_reset_url(to_email=to_email, code=code)

        message.set_content(_INITIAL_PASSWORD_SETUP_TEXT.format(reset_url=reset_url))
        message.add_alternative(
            _INITIAL_PASSWORD_SETUP_HTML.format(
                reset_url=escape(reset_url, quote=True),
            ),
            subtype="html",
        )

        await self._send(message=message, to_email=to_email)

    async def _send(self, message: EmailMessage, to_email: str) -> None:
        """Send a prepared email. SMTP failures are logged and never propagated."""
        try:
            await aiosmtplib.send(
                message,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USERNAME or None,
                password=settings.SMTP_PASSWORD or None,
                start_tls=True,
            )
        except Exception:
            # Swallow: endpoint must stay 200 to avoid leaking whether the email exists.
            logger.exception("Failed to send password reset email to %s", to_email)

    def _format_from(self) -> str:
        """Build the From header from the authenticated account."""
        if settings.SMTP_FROM_NAME:
            return f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USERNAME}>"
        return settings.SMTP_USERNAME

    def _build_password_reset_url(self, to_email: str, code: str) -> str:
        """Build a reset URL whose sensitive parameters stay in the URL fragment."""
        fragment = urlencode({"email": to_email, "code": code})
        return f"{settings.FRONTEND_URL.rstrip('/')}/forgot-password#{fragment}"
