"""Student service for student registration."""

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import ClassEnum, StudentProfile, UserProfile, WellBeing
from md_backend.utils.security import hash_password


class StudentService:
    """Service for student operations."""

    async def create_student(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        birth_date: datetime.date,
        student_class: ClassEnum,
        session: AsyncSession,
        phone_number: str | None = None,
        school_id: uuid.UUID | None = None,
    ) -> dict | None:
        """Create a student atomically across user_profile and student_profile."""
        existing = await session.execute(select(UserProfile).where(UserProfile.email == email))
        if existing.scalar_one_or_none() is not None:
            return None

        hashed = hash_password(password)

        try:
            user_profile = UserProfile(
                first_name=first_name,
                last_name=last_name,
                email=email,
                password=hashed,
                phone_number=phone_number,
            )
            student_profile = StudentProfile(
                user=user_profile,
                birth_date=birth_date,
                student_class=student_class,
                school_id=school_id,
            )
            session.add(user_profile)
            session.add(student_profile)
            await session.commit()
            await session.refresh(user_profile)
            await session.refresh(student_profile)
        except IntegrityError:
            await session.rollback()
            return None

        return self._to_dict(user_profile, student_profile)

    async def get_students(
        self,
        session: AsyncSession,
        name: str | None = None,
        email: str | None = None,
        page: int = 1,
        size: int = 10,
    ) -> list[dict]:
        """List active students with optional filters and pagination."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(UserProfile.is_active.is_(True))
        )

        if name:
            query = query.where(
                UserProfile.first_name.ilike(f"%{name}%") | UserProfile.last_name.ilike(f"%{name}%")
            )

        if email:
            query = query.where(UserProfile.email.ilike(f"%{email}%"))

        query = query.offset((page - 1) * size).limit(size)

        result = await session.execute(query)
        rows = result.all()

        return [self._to_dict(user, student) for user, student in rows]

    async def get_student_by_id(self, session: AsyncSession, student_id: uuid.UUID) -> dict | None:
        """Get a student by user_id."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(StudentProfile.user_id == student_id)
        )

        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return None

        user_profile, student_profile = row
        return self._to_dict(user_profile, student_profile)

    async def update_student(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        data: dict,
    ) -> dict | None:
        """Update a student's data. Returns None if not found."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(StudentProfile.user_id == student_id)
        )
        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return None

        user_profile, student_profile = row

        user_fields = {"first_name", "last_name", "phone_number"}
        student_fields = {"birth_date", "student_class", "school_id"}

        for field, value in data.items():
            if value is None:
                continue
            if field in user_fields:
                setattr(user_profile, field, value)
            elif field in student_fields:
                setattr(student_profile, field, value)

        try:
            await session.commit()
            await session.refresh(user_profile)
            await session.refresh(student_profile)
        except Exception:
            await session.rollback()
            raise

        return self._to_dict(user_profile, student_profile)

    async def deactivate_student(self, session: AsyncSession, student_id: uuid.UUID) -> bool:
        """Soft delete a student by setting is_active to False."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(StudentProfile.user_id == student_id)
        )
        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return False

        user_profile, student_profile = row
        now = datetime.datetime.now(datetime.UTC)
        user_profile.is_active = False
        user_profile.deactivated_at = now
        student_profile.deactivated_at = now

        await session.commit()
        return True

    async def upsert_well_being(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        date: datetime.date,
        humor: str | None,
        online_activity_minutes: int | None,
        sleep_hours: float | None,
    ) -> dict:
        """Atomically insert or update a well-being record (upsert).

        Uses a single database command with ON CONFLICT to avoid a prior SELECT.
        Compatible with both SQLite (tests) and PostgreSQL (production).
        """
        dialect_name = session.bind.dialect.name if session.bind else "sqlite"  # type: ignore[union-attr]

        if dialect_name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = pg_insert(WellBeing).values(
                student_id=student_id,
                date=date,
                humor=humor,
                online_activity_minutes=online_activity_minutes,
                sleep_hours=sleep_hours,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["student_id", "date"],
                set_={
                    "humor": stmt.excluded.humor,
                    "online_activity_minutes": stmt.excluded.online_activity_minutes,
                    "sleep_hours": stmt.excluded.sleep_hours,
                },
            )
        else:
            # SQLite (used in tests) — INSERT OR REPLACE handles the composite PK conflict
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            stmt = sqlite_insert(WellBeing).values(
                student_id=student_id,
                date=date,
                humor=humor,
                online_activity_minutes=online_activity_minutes,
                sleep_hours=sleep_hours,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["student_id", "date"],
                set_={
                    "humor": stmt.excluded.humor,
                    "online_activity_minutes": stmt.excluded.online_activity_minutes,
                    "sleep_hours": stmt.excluded.sleep_hours,
                },
            )

        await session.execute(stmt)
        await session.commit()

        result = await session.execute(
            select(WellBeing).where(
                WellBeing.student_id == student_id,
                WellBeing.date == date,
            )
        )
        record = result.scalar_one()
        return self._well_being_to_dict(record)

    async def get_well_being(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        date: datetime.date,
    ) -> dict | None:
        """Return a student's well-being record for a given date, or None if not found."""
        result = await session.execute(
            select(WellBeing).where(
                WellBeing.student_id == student_id,
                WellBeing.date == date,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._well_being_to_dict(record)

    async def get_well_being_range(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        from_date: datetime.date,
        to_date: datetime.date,
    ) -> list[dict]:
        """Return a student's well-being records in date order for a date range."""
        result = await session.execute(
            select(WellBeing)
            .where(
                WellBeing.student_id == student_id,
                WellBeing.date >= from_date,
                WellBeing.date <= to_date,
            )
            .order_by(WellBeing.date.asc())
        )
        return [self._well_being_to_dict(record) for record in result.scalars()]

    def _well_being_to_dict(self, record: WellBeing) -> dict:
        """Map a WellBeing ORM object to a serialisable dict."""
        return {
            "student_id": str(record.student_id),
            "date": record.date.isoformat(),
            "humor": record.humor.value if record.humor else None,
            "online_activity_minutes": record.online_activity_minutes,
            "sleep_hours": float(record.sleep_hours) if record.sleep_hours is not None else None,
        }

    def _to_dict(self, user_profile: UserProfile, student_profile: StudentProfile) -> dict:
        """Map user_profile and student_profile to a full response dict."""
        return {
            "id": str(student_profile.user_id),
            "user_id": str(user_profile.id),
            "first_name": user_profile.first_name,
            "last_name": user_profile.last_name,
            "email": user_profile.email,
            "phone_number": user_profile.phone_number or "",
            "birth_date": (
                student_profile.birth_date.isoformat() if student_profile.birth_date else ""
            ),
            "student_class": student_profile.student_class.value,
            "school_id": str(student_profile.school_id) if student_profile.school_id else "",
            "is_active": user_profile.is_active,
            "created_at": user_profile.created_at.isoformat() if user_profile.created_at else None,
        }
