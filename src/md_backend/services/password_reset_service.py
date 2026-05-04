"""Service for password reset requests and confirmations."""

import datetime
import secrets

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import PasswordResetCode, UserProfile
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

    async def request_reset(self, email: str, session: AsyncSession) -> dict:
        """Create a reset code for an existing user. Invalidates any prior active codes."""
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
            expires_at = _ensure_aware_utc(reset_entry.expires_at)
            if expires_at <= now:
                continue
            if await verify_password(code, reset_entry.code_hash):
                return reset_entry

        return None
