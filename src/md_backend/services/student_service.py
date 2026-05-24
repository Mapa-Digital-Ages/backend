"""Student service for student registration."""

import datetime
import uuid

from helper_backend.utils.logger import get_logger
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from md_backend.models.db_models import (
    ClassEnum,
    GuardianProfile,
    SchoolProfile,
    StudentGuardian,
    StudentProfile,
    TaskStatusEnum,
    UserProfile,
)
from md_backend.utils.security import hash_password

logger = get_logger(__name__)

_logger_extra = {
    "component_name": "student_service",
    "component_version": "v1",
}

_TASK_STATUS_TO_FRONTEND = {
    TaskStatusEnum.DONE: "done",
    TaskStatusEnum.PENDING: "pending",
    TaskStatusEnum.ADJUST: "adjust",
}


def get_week_bounds(
    reference: datetime.date | None = None,
) -> tuple[datetime.datetime, datetime.datetime]:
    """Return (week_start, week_end) as UTC-aware datetimes for the current week."""
    if reference is None:
        reference = datetime.datetime.now(datetime.UTC).date()

    days_since_sunday = (reference.weekday() + 1) % 7
    sunday = reference - datetime.timedelta(days=days_since_sunday)
    saturday = sunday + datetime.timedelta(days=6)

    week_start = datetime.datetime(
        sunday.year,
        sunday.month,
        sunday.day,
        0,
        0,
        0,
        tzinfo=datetime.UTC,
    )

    week_end = datetime.datetime(
        saturday.year,
        saturday.month,
        saturday.day,
        23,
        59,
        59,
        999999,
        tzinfo=datetime.UTC,
    )

    return week_start, week_end


def _task_with_subject_to_dict(task, subject) -> dict:
    """Serialize a (Task, Subject) row to the calendar contract dict."""
    return {
        "id": task.id,
        "date": task.date.isoformat() if task.date else None,
        "title": task.title,
        "status": (
            _TASK_STATUS_TO_FRONTEND.get(task.task_status, "pending")
            if task.task_status
            else "pending"
        ),
        "subject": {
            "id": subject.id,
            "label": subject.name,
        },
    }


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
        """Create a student atomically."""
        logger.info(
            "Creating student",
            extra={
                **_logger_extra,
                "email": email,
                "student_class": student_class.value,
            },
        )

        existing = await session.execute(select(UserProfile).where(UserProfile.email == email))

        if existing.scalar_one_or_none() is not None:
            logger.warning(
                "Student creation failed: email already exists",
                extra={
                    **_logger_extra,
                    "email": email,
                },
            )

            return None

        hashed = await hash_password(password)

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

            logger.info(
                "Student created successfully",
                extra={
                    **_logger_extra,
                    "student_id": str(student_profile.user_id),
                    "email": email,
                },
            )

        except IntegrityError:
            await session.rollback()

            logger.exception(
                "Student creation failed due to integrity error",
                extra={
                    **_logger_extra,
                    "email": email,
                },
            )

            return None

        return self._to_dict(user_profile, student_profile)

    async def _fetch_school_names(
        self,
        session: AsyncSession,
        school_ids: set[uuid.UUID],
    ) -> dict[uuid.UUID, str]:
        """Fetch school names for a set of school_ids."""
        if not school_ids:
            return {}

        school_user = UserProfile

        query = (
            select(
                SchoolProfile.user_id,
                school_user.first_name,
                school_user.last_name,
            )
            .join(
                school_user,
                school_user.id == SchoolProfile.user_id,
            )
            .where(SchoolProfile.user_id.in_(school_ids))
        )

        rows = (await session.execute(query)).all()

        return {row[0]: f"{row[1]} {row[2]}".strip() for row in rows}

    async def _fetch_guardian_info(
        self,
        session: AsyncSession,
        student_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
        """Fetch first active guardian (id, name) per student."""
        if not student_ids:
            return {}

        query = (
            select(
                StudentGuardian.student_id,
                GuardianProfile.user_id,
                UserProfile.first_name,
                UserProfile.last_name,
            )
            .select_from(StudentGuardian)
            .join(
                GuardianProfile,
                GuardianProfile.user_id == StudentGuardian.guardian_id,
            )
            .join(
                UserProfile,
                UserProfile.id == GuardianProfile.user_id,
            )
            .where(
                StudentGuardian.student_id.in_(student_ids),
                StudentGuardian.deactivated_at.is_(None),
            )
        )

        rows = (await session.execute(query)).all()

        result: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}

        for student_id, guardian_id, first_name, last_name in rows:
            if student_id not in result:
                result[student_id] = (
                    guardian_id,
                    f"{first_name} {last_name}".strip(),
                )

        return result

    async def get_students(
        self,
        session: AsyncSession,
        name: str | None = None,
        email: str | None = None,
        page: int = 1,
        size: int = 10,
    ) -> dict:
        """List active students with optional filters and pagination."""
        logger.info(
            "Listing students",
            extra={
                **_logger_extra,
                "page": page,
                "size": size,
                "name_filter": name,
                "email_filter": email,
            },
        )

        base_conditions = [
            UserProfile.is_active.is_(True),
            StudentProfile.deactivated_at.is_(None),
        ]

        extra_filters = []

        if name:
            extra_filters.append(
                UserProfile.first_name.ilike(f"%{name}%") | UserProfile.last_name.ilike(f"%{name}%")
            )

        if email:
            extra_filters.append(UserProfile.email.ilike(f"%{email}%"))

        count_query = (
            select(func.count(UserProfile.id))
            .join(
                StudentProfile,
                StudentProfile.user_id == UserProfile.id,
            )
            .where(*base_conditions, *extra_filters)
        )

        total: int = (await session.execute(count_query)).scalar() or 0

        items_query = (
            select(UserProfile, StudentProfile)
            .join(
                StudentProfile,
                StudentProfile.user_id == UserProfile.id,
            )
            .where(*base_conditions, *extra_filters)
            .order_by(
                func.lower(UserProfile.first_name),
                func.lower(UserProfile.last_name),
                UserProfile.id,
            )
            .offset((page - 1) * size)
            .limit(size)
        )

        rows = (await session.execute(items_query)).all()

        school_ids = {student.school_id for _, student in rows if student.school_id is not None}

        student_ids = [student.user_id for _, student in rows]

        school_names = await self._fetch_school_names(
            session,
            school_ids,
        )

        guardian_info = await self._fetch_guardian_info(
            session,
            student_ids,
        )

        items = []

        for user, student in rows:
            guardian = guardian_info.get(student.user_id)

            items.append(
                self._to_dict(
                    user,
                    student,
                    school_name=(
                        school_names.get(student.school_id) if student.school_id else None
                    ),
                    guardian_id=(str(guardian[0]) if guardian else None),
                    guardian_name=(guardian[1] if guardian else None),
                )
            )

        total_pages = (total + size - 1) // size if size > 0 else 0

        logger.info(
            "Students listed successfully",
            extra={
                **_logger_extra,
                "students_count": len(rows),
            },
        )

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": size,
            "total_pages": total_pages,
        }

    async def count_students(
        self,
        session: AsyncSession,
        name: str | None = None,
    ) -> int:
        """Return the total count of active students."""
        conditions: list[ColumnElement[bool]] = [
            UserProfile.is_active.is_(True),
            StudentProfile.deactivated_at.is_(None),
        ]

        if name:
            conditions.append(
                UserProfile.first_name.ilike(f"%{name}%") | UserProfile.last_name.ilike(f"%{name}%")
            )

        query = (
            select(func.count(UserProfile.id))
            .join(
                StudentProfile,
                StudentProfile.user_id == UserProfile.id,
            )
            .where(*conditions)
        )

        return (await session.execute(query)).scalar() or 0

    async def get_student_by_id(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
    ) -> dict | None:
        """Get a student by user_id."""
        logger.info(
            "Getting student by id",
            extra={
                **_logger_extra,
                "student_id": str(student_id),
            },
        )

        query = (
            select(UserProfile, StudentProfile)
            .join(
                StudentProfile,
                StudentProfile.user_id == UserProfile.id,
            )
            .where(
                StudentProfile.user_id == student_id,
                UserProfile.is_active.is_(True),
                StudentProfile.deactivated_at.is_(None),
            )
        )

        result = await session.execute(query)

        row = result.one_or_none()

        if row is None:
            logger.warning(
                "Student not found",
                extra={
                    **_logger_extra,
                    "student_id": str(student_id),
                },
            )

            return None

        user_profile, student_profile = row

        school_ids = {student_profile.school_id} if student_profile.school_id else set()

        school_names = await self._fetch_school_names(
            session,
            school_ids,
        )

        guardian_info = await self._fetch_guardian_info(
            session,
            [student_profile.user_id],
        )

        guardian = guardian_info.get(student_profile.user_id)

        return self._to_dict(
            user_profile,
            student_profile,
            school_name=(
                school_names.get(student_profile.school_id) if student_profile.school_id else None
            ),
            guardian_id=(str(guardian[0]) if guardian else None),
            guardian_name=(guardian[1] if guardian else None),
        )

    async def update_student(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        data: dict,
    ) -> dict | None:
        """Update a student."""
        query = (
            select(UserProfile, StudentProfile)
            .join(
                StudentProfile,
                StudentProfile.user_id == UserProfile.id,
            )
            .where(StudentProfile.user_id == student_id)
        )

        result = await session.execute(query)

        row = result.one_or_none()

        if row is None:
            return None

        user_profile, student_profile = row

        user_fields = {
            "first_name",
            "last_name",
            "phone_number",
        }

        student_fields = {
            "birth_date",
            "student_class",
            "school_id",
        }

        for field, value in data.items():
            if value is None:
                continue

            if field in user_fields:
                setattr(user_profile, field, value)

            elif field in student_fields:
                setattr(student_profile, field, value)

        if "guardian_id" in data:
            new_guardian_id = data.pop("guardian_id")

            now = datetime.datetime.now(datetime.UTC)

            await session.execute(
                update(StudentGuardian)
                .where(
                    StudentGuardian.student_id == student_id,
                    StudentGuardian.deactivated_at.is_(None),
                )
                .values(deactivated_at=now)
            )

            if new_guardian_id is not None:
                existing = await session.execute(
                    select(StudentGuardian).where(
                        StudentGuardian.student_id == student_id,
                        StudentGuardian.guardian_id == new_guardian_id,
                    )
                )

                existing_link = existing.scalar_one_or_none()

                if existing_link is not None:
                    existing_link.deactivated_at = None

                else:
                    session.add(
                        StudentGuardian(
                            student_id=student_id,
                            guardian_id=new_guardian_id,
                        )
                    )

        try:
            await session.commit()

            await session.refresh(user_profile)
            await session.refresh(student_profile)

        except Exception:
            await session.rollback()
            raise

        school_ids = {student_profile.school_id} if student_profile.school_id else set()

        school_names = await self._fetch_school_names(
            session,
            school_ids,
        )

        guardian_info = await self._fetch_guardian_info(
            session,
            [student_profile.user_id],
        )

        guardian = guardian_info.get(student_profile.user_id)

        return self._to_dict(
            user_profile,
            student_profile,
            school_name=(
                school_names.get(student_profile.school_id) if student_profile.school_id else None
            ),
            guardian_id=(str(guardian[0]) if guardian else None),
            guardian_name=(guardian[1] if guardian else None),
        )
