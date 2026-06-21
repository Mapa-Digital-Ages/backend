"""Email sender used by transactional flows (password reset, etc.)."""

import logging
from email.message import EmailMessage
from html import escape
from urllib.parse import urlencode

import aiosmtplib

from md_backend.utils.settings import settings

logger = logging.getLogger(__name__)

_PASSWORD_RESET_SUBJECT = "Defina sua senha — Mapa Digital"

_PASSWORD_RESET_TEXT = (
    "Olá,\n\n"
    "Acesse o link abaixo para definir ou redefinir a senha da sua conta no Mapa Digital:\n\n"
    "{reset_url}\n\n"
    "{expiration_text} Se você não esperava este email, ignore esta mensagem."
)

_PASSWORD_RESET_HTML = (
    "<p>Olá,</p>"
    "<p>Acesse o link abaixo para definir ou redefinir a senha da sua conta no Mapa Digital.</p>"
    '<p><a href="{reset_url}">Definir minha senha</a></p>'
    "<p>{expiration_text}"
    " Se você não esperava este email, ignore esta mensagem.</p>"
)


class EmailSender:
    """Send transactional emails via SMTP, with a safe no-op fallback for dev/tests."""

    async def send_password_reset(
        self,
        to_email: str,
        code: str,
        expires_in_minutes: int | None = 15,
    ) -> None:
        """Send a single-use password setup link. Never raises — failures are logged."""
        if not (settings.SMTP_USERNAME and settings.SMTP_PASSWORD):
            logger.info("[email noop] reset code for %s: %s", to_email, code)
            return

        message = EmailMessage()
        message["Subject"] = _PASSWORD_RESET_SUBJECT
        message["From"] = self._format_from()
        message["To"] = to_email
        reset_url = self._build_password_reset_url(to_email=to_email, code=code)
        if expires_in_minutes is None:
            expiration_text = "O link permanece válido até você definir sua senha."
            html_expiration_text = "O link permanece válido até você definir sua senha."
        else:
            expiration_text = f"O link expira em {expires_in_minutes} minutos."
            html_expiration_text = (
                f"O link expira em <strong>{expires_in_minutes} minutos</strong>."
            )

        message.set_content(
            _PASSWORD_RESET_TEXT.format(
                reset_url=reset_url,
                expiration_text=expiration_text,
            )
        )
        message.add_alternative(
            _PASSWORD_RESET_HTML.format(
                reset_url=escape(reset_url, quote=True),
                expiration_text=html_expiration_text,
            ),
            subtype="html",
        )

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
