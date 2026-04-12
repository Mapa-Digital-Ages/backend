"""Admin service for user management."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import RoleEnum, User, UserStatus


class AdminService:
    """Service for admin operations on users."""

    async def list_users(
        self,
        session: AsyncSession,
        status_filter: UserStatus | None = None,
        role: RoleEnum | None = None,
    ) -> list[dict]:
        """List all users, optionally filtered by status."""
        query = select(User).order_by(User.created_at.desc())
        if status_filter is not None:
            query = query.where(User.status == status_filter)
        if role is not None:
            query = query.where(User.role == role)

        result = await session.execute(query)
        users = result.scalars().all()

        return [
            {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "status": user.status.value,
                "role": user.role,
                "is_superadmin": user.is_superadmin,
                "created_at": user.created_at.isoformat(),
            }
            for user in users
        ]

    async def update_user_status(
        self, session: AsyncSession, email: str, new_status: UserStatus
    ) -> dict | None:
        """Update a user's approval status. Returns None if user not found."""
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user is None:
            return None

        if user.is_superadmin:
            return {"error": "Nao e possivel alterar status de um superadmin"}

        user.status = new_status
        await session.commit()

        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "status": user.status.value,
            "role": user.role,
            "is_superadmin": user.is_superadmin,
            "created_at": user.created_at.isoformat(),
        }
