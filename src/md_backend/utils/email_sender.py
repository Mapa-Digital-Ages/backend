"""Email sender used by transactional flows (password reset, etc.)."""

import logging
from email.message import EmailMessage

import aiosmtplib

from md_backend.utils.settings import settings

logger = logging.getLogger(__name__)

_PASSWORD_RESET_SUBJECT = "Seu código de redefinição de senha"

_PASSWORD_RESET_TEXT = (
    "Olá,\n\n"
    "Recebemos uma solicitação para redefinir a senha da sua conta no Mapa Digital.\n\n"
    "Seu código de redefinição é: {code}\n\n"
    "O código expira em 15 minutos. Se você não solicitou a redefinição, ignore este email."
)

_PASSWORD_RESET_HTML = (
    "<p>Olá,</p>"
    "<p>Recebemos uma solicitação para redefinir a senha da sua conta no Mapa Digital.</p>"
    "<p>Seu código de redefinição é:"
    ' <strong style="font-size:1.4em;letter-spacing:0.15em">{code}</strong></p>'
    "<p>O código expira em <strong>15 minutos</strong>."
    " Se você não solicitou a redefinição, ignore este email.</p>"
)


class EmailSender:
    """Send transactional emails via SMTP, with a safe no-op fallback for dev/tests."""

    async def send_password_reset(self, to_email: str, code: str) -> None:
        """Send the password reset code email. Never raises — failures are logged."""
        if not (settings.SMTP_USERNAME and settings.SMTP_PASSWORD):
            logger.info("[email noop] reset code for %s: %s", to_email, code)
            return

        message = EmailMessage()
        message["Subject"] = _PASSWORD_RESET_SUBJECT
        message["From"] = self._format_from()
        message["To"] = to_email
        message.set_content(_PASSWORD_RESET_TEXT.format(code=code))
        message.add_alternative(_PASSWORD_RESET_HTML.format(code=code), subtype="html")

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
