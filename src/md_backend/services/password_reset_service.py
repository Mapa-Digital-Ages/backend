"""Service for password reset requests and confirmations."""

import datetime
import secrets

from fastapi import BackgroundTasks
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import PasswordResetCode, UserProfile
from md_backend.utils.email_sender import EmailSender
from md_backend.utils.security import hash_password, verify_password

RESET_CODE_TTL_MINUTES = 15


def _utc_now() -> datetime.datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.datetime.now(datetime.UTC)


def _ensure_aware_utc(value: datetime.datetime) -> datetime.datetime:
    """Normalize database datetimes to timezone-aware UTC values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.UTC)
    return value.astimezone(datetime.UTC)


def _generate_reset_code() -> str:
    """Generate a six-digit reset code."""
    return f"{secrets.randbelow(1_000_000):06d}"


class PasswordResetService:
    """Business logic for password reset code lifecycle."""

    def __init__(self, email_sender: EmailSender | None = None) -> None:
        """Initialize with an optional sender override (defaults to the real EmailSender)."""
        self._email_sender = email_sender or EmailSender()

    async def prepare_initial_password_setup(
        self,
        user_id: object,
        session: AsyncSession,
    ) -> str:
        """Add a reset code for a newly created user to the current transaction."""
        reset_code = _generate_reset_code()
        session.add(
            PasswordResetCode(
                user_id=user_id,
                code_hash=await hash_password(reset_code),
                expires_at=None,
            )
        )
        return reset_code

    async def dispatch_initial_password_setup_email(
        self,
        email: str,
        code: str,
        background_tasks: BackgroundTasks | None = None,
    ) -> None:
        """Send a non-expiring, single-use initial password setup link."""
        if background_tasks is not None:
            background_tasks.add_task(
                self._email_sender.send_password_reset,
                to_email=email,
                code=code,
                expires_in_minutes=None,
            )
            return

        await self._email_sender.send_password_reset(
            to_email=email,
            code=code,
            expires_in_minutes=None,
        )

    async def dispatch_reset_email(
        self,
        email: str,
        code: str,
        background_tasks: BackgroundTasks | None = None,
    ) -> None:
        """Send or enqueue the email for a previously persisted reset code."""
        if background_tasks is not None:
            background_tasks.add_task(
                self._email_sender.send_password_reset,
                to_email=email,
                code=code,
            )
            return

        await self._email_sender.send_password_reset(to_email=email, code=code)

    async def request_reset(
        self,
        email: str,
        session: AsyncSession,
        background_tasks: BackgroundTasks | None = None,
    ) -> dict:
        """Create a reset code for an existing user. Invalidates any prior active codes.

        When ``background_tasks`` is provided, the email is dispatched after the HTTP
        response is sent so the endpoint returns quickly. Without it, the email is
        awaited inline (used in tests and scripts).
        """
        user = await self._get_user_by_email(email=email, session=session)
        reset_code = _generate_reset_code()

        if user is None:
            return {"detail": "Password reset code generated"}

        now = _utc_now()

        # Invalidate any existing active codes (limit to 1 active per user)
        await session.execute(
            update(PasswordResetCode)
            .where(
                PasswordResetCode.user_id == user.id,
                PasswordResetCode.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )

        reset_entry = PasswordResetCode(
            user_id=user.id,
            code_hash=await hash_password(reset_code),
            expires_at=now + datetime.timedelta(minutes=RESET_CODE_TTL_MINUTES),
        )
        session.add(reset_entry)
        await session.commit()

        await self.dispatch_reset_email(
            email=email,
            code=reset_code,
            background_tasks=background_tasks,
        )

        return {"detail": "Password reset code generated"}

    async def confirm_reset(
        self, email: str, code: str, new_password: str, session: AsyncSession
    ) -> bool:
        """Update the user password when a valid reset code is provided."""
        user = await self._get_user_by_email(email=email, session=session)
        if user is None:
            return False

        reset_entry = await self._get_valid_reset_entry(user_id=user.id, code=code, session=session)
        if reset_entry is None:
            return False

        now = _utc_now()
        user.password = await hash_password(new_password)

        # Consume ALL active codes for this user (not just the matched one)
        await session.execute(
            update(PasswordResetCode)
            .where(
                PasswordResetCode.user_id == user.id,
                PasswordResetCode.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        await session.commit()
        return True

    async def _get_user_by_email(self, email: str, session: AsyncSession) -> UserProfile | None:
        """Fetch a user by email."""
        result = await session.execute(select(UserProfile).where(UserProfile.email == email))
        return result.scalar_one_or_none()

    async def _get_valid_reset_entry(
        self, user_id: object, code: str, session: AsyncSession
    ) -> PasswordResetCode | None:
        """Fetch the newest matching active reset code for a user."""
        now = _utc_now()
        result = await session.execute(
            select(PasswordResetCode)
            .where(
                PasswordResetCode.user_id == user_id,
                PasswordResetCode.consumed_at.is_(None),
            )
            .order_by(PasswordResetCode.created_at.desc())
        )

        for reset_entry in result.scalars():
            expires_at = reset_entry.expires_at
            if expires_at is not None and _ensure_aware_utc(expires_at) <= now:
                continue
            if await verify_password(code, reset_entry.code_hash):
                return reset_entry

        return None
