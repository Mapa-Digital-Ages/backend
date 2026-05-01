"""School Services - handles atomic creation of school accounts."""

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import SchoolProfile, StudentProfile, UserProfile
from md_backend.utils.security import hash_password


class SchoolService:
    """Service for school-related operations."""

    async def create_school(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        is_private: bool,
        session: AsyncSession,
        phone_number: str | None = None,
        requested_spots: int | None = None,
    ) -> dict | None:
        """Create a school atomically (user_profile + school_profile).

        Returns the created school dict, or None if the e-mail already exists.
        """
        existing = await session.execute(select(UserProfile).where(UserProfile.email == email))
        if existing.scalar_one_or_none() is not None:
            return None

        hashed = hash_password(password)
        user = UserProfile(
            email=email,
            password=hashed,
            first_name=first_name,
            last_name=last_name,
            phone_number=phone_number,
        )
        school = SchoolProfile(
            user=user,
            is_private=is_private,
            requested_spots=requested_spots,
        )
        session.add(user)
        session.add(school)

        await session.commit()
        await session.refresh(user)
        await session.refresh(school)

        return self._build_school_dict(user, school, student_count=0)

    def _build_school_dict(
        self, user: UserProfile, school: SchoolProfile, student_count: int
    ) -> dict:
        """Build the response dict without exposing the password."""
        full_name = f"{user.first_name} {user.last_name}".strip()
        return {
            "user_id": str(user.id),
            "email": user.email,
            "name": full_name,
            "is_private": school.is_private,
            "requested_spots": school.requested_spots,
            "is_active": user.is_active,
            "deactivated_at": school.deactivated_at.isoformat() if school.deactivated_at else None,
            "created_at": user.created_at.isoformat(),
            "student_count": student_count,
        }

    def _student_count_subq(self):
        """Correlated subquery counting students per school."""
        return (
            select(func.count(StudentProfile.user_id))
            .where(StudentProfile.school_id == SchoolProfile.user_id)
            .correlate(SchoolProfile)
            .scalar_subquery()
        )

    async def list_schools(
        self,
        session: AsyncSession,
        page: int = 1,
        size: int = 20,
        name: str | None = None,
    ) -> dict:
        """Return a paginated list of active schools with student count."""
        count_subq = self._student_count_subq()

        query = (
            select(UserProfile, SchoolProfile, count_subq.label("student_count"))
            .join(SchoolProfile, SchoolProfile.user_id == UserProfile.id)
            .where(UserProfile.is_active.is_(True))
        )

        if name:
            query = query.where(
                UserProfile.first_name.ilike(f"%{name}%") | UserProfile.last_name.ilike(f"%{name}%")
            )

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar_one()

        offset = (page - 1) * size
        result = await session.execute(query.offset(offset).limit(size))
        rows = result.all()

        items = [
            self._build_school_dict(user, school, student_count)
            for user, school, student_count in rows
        ]

        return {"items": items, "total": total, "page": page, "size": size}

    async def get_school_by_id(
        self,
        school_id: uuid.UUID,
        session: AsyncSession,
    ) -> dict | None:
        """Return a single school by its user_id, or None if not found."""
        count_subq = self._student_count_subq()

        query = (
            select(UserProfile, SchoolProfile, count_subq.label("student_count"))
            .join(SchoolProfile, SchoolProfile.user_id == UserProfile.id)
            .where(SchoolProfile.user_id == school_id)
        )

        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return None

        user, school, student_count = row
        return self._build_school_dict(user, school, student_count)

    async def update_school(
        self,
        school_id: uuid.UUID,
        first_name: str | None,
        last_name: str | None,
        email: str | None,
        is_private: bool | None,
        requested_spots: int | None,
        session: AsyncSession,
    ) -> dict | None | str:
        """Update school fields partially. Returns dict, None (not found), or 'email_conflict'."""
        result = await session.execute(
            select(UserProfile, SchoolProfile)
            .join(SchoolProfile, SchoolProfile.user_id == UserProfile.id)
            .where(SchoolProfile.user_id == school_id)
        )
        row = result.one_or_none()

        if row is None:
            return None

        user, school = row

        if email is not None and email != user.email:
            conflict = await session.execute(select(UserProfile).where(UserProfile.email == email))
            if conflict.scalar_one_or_none() is not None:
                return "email_conflict"
            user.email = email

        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name

        if is_private is not None:
            school.is_private = is_private

        if requested_spots is not None:
            school.requested_spots = requested_spots

        await session.commit()
        await session.refresh(user)
        await session.refresh(school)

        count_result = await session.execute(
            select(func.count(StudentProfile.user_id)).where(StudentProfile.school_id == school_id)
        )
        student_count = count_result.scalar_one()

        return self._build_school_dict(user, school, student_count)

    async def deactivate_school(
        self,
        school_id: uuid.UUID,
        session: AsyncSession,
    ) -> bool:
        """Soft delete: set is_active=False on user and deactivated_at on school."""
        result = await session.execute(
            select(UserProfile, SchoolProfile)
            .join(SchoolProfile, SchoolProfile.user_id == UserProfile.id)
            .where(SchoolProfile.user_id == school_id)
        )
        row = result.one_or_none()

        if row is None:
            return False

        user, school = row
        now = datetime.datetime.now(datetime.UTC)
        user.is_active = False
        user.deactivated_at = now
        school.deactivated_at = now

        await session.commit()
        return True
