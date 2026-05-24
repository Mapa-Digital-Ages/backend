"""Login service for user authentication."""

from helper_backend.utils.logger import get_logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from md_backend.models.db_models import (
    GuardianStatusEnum,
    LoginHistory,
    UserProfile,
)
from md_backend.utils.security import (
    _hash_sync,
    create_access_token,
    verify_password,
)

logger = get_logger(__name__)
_logger_extra = {
    "component_name": "login_service",
    "component_version": "v1",
}

_DUMMY_HASH: str = _hash_sync("__dummy_timing_guard__")


def _derive_role(user: UserProfile) -> str:
    if user.admin_profile is not None:
        return "admin"

    if user.student_profile is not None:
        return "student"

    return "guardian"


class LoginService:
    """Service for handling user login."""

    async def login(
        self,
        email: str,
        password: str,
        session: AsyncSession,
        ip: str | None = None,
    ) -> dict:
        """Authenticate user and return JWT token or error dict."""
        logger.info(
            "Login attempt",
            extra={
                **_logger_extra,
                "email": email,
                "ip": ip,
            },
        )

        result = await session.execute(
            select(UserProfile)
            .options(
                selectinload(UserProfile.guardian_profile),
                selectinload(UserProfile.admin_profile),
                selectinload(UserProfile.student_profile),
            )
            .where(UserProfile.email == email)
        )

        user = result.scalar_one_or_none()

        if user is None:
            logger.warning(
                "Login failed: user not found",
                extra={
                    **_logger_extra,
                    "email": email,
                    "ip": ip,
                },
            )

            await verify_password(password, _DUMMY_HASH)

            return {"error": "invalid_credentials"}

        if not await verify_password(password, user.password):
            logger.warning(
                "Login failed: invalid password",
                extra={
                    **_logger_extra,
                    "email": email,
                    "user_id": str(user.id),
                    "ip": ip,
                },
            )

            return {"error": "invalid_credentials"}

        if not user.is_active:
            logger.warning(
                "Login failed: account deactivated",
                extra={
                    **_logger_extra,
                    "email": email,
                    "user_id": str(user.id),
                    "ip": ip,
                },
            )

            return {"error": "Account deactivated"}

        if user.guardian_profile is not None:
            if user.guardian_profile.guardian_status == GuardianStatusEnum.WAITING:
                logger.warning(
                    "Login blocked: guardian waiting approval",
                    extra={
                        **_logger_extra,
                        "email": email,
                        "user_id": str(user.id),
                    },
                )

                return {"error": "WAITING"}

            if user.guardian_profile.guardian_status == GuardianStatusEnum.REJECTED:
                logger.warning(
                    "Login blocked: guardian rejected",
                    extra={
                        **_logger_extra,
                        "email": email,
                        "user_id": str(user.id),
                    },
                )

                return {"error": "REJECTED"}

        session.add(
            LoginHistory(
                user_id=user.id,
                ip=ip,
            )
        )

        await session.commit()

        token = create_access_token(
            {
                "sub": str(user.id),
                "user_id": str(user.id),
            }
        )

        logger.info(
            "Login successful",
            extra={
                **_logger_extra,
                "email": email,
                "user_id": str(user.id),
                "role": _derive_role(user),
                "ip": ip,
            },
        )

        name = f"{user.first_name} {user.last_name}".strip()

        return {
            "token": token,
            "role": _derive_role(user),
            "email": user.email,
            "name": name,
        }
