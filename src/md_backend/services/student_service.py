"""Student service for student registration."""

import datetime
import logging
import uuid

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
    Subject,
    Task,
    TaskStatusEnum,
    UserProfile,
    WellBeing,
)
from md_backend.utils.security import hash_password

logger = logging.getLogger(__name__)

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
    """Return UTC-aware (week_start, week_end) for the week containing reference."""
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


def _task_with_subject_to_dict(task: Task, subject: Subject) -> dict:
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

    def _to_dict(
        self,
        user: UserProfile,
        student: StudentProfile,
        school_name: str | None = None,
        guardian_id: str | None = None,
        guardian_name: str | None = None,
    ) -> dict:
        """Serialize user and student profiles into a safe response dict."""
        first_name = user.first_name or ""
        last_name = user.last_name or ""
        full_name = f"{first_name} {last_name}".strip()

        return {
            "id": str(student.user_id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": full_name if full_name else None,
            "phone_number": user.phone_number,
            "birth_date": student.birth_date.isoformat() if student.birth_date else None,
            "student_class": student.student_class.value if student.student_class else None,
            "school_id": str(student.school_id) if student.school_id else None,
            "school_name": school_name,
            "guardian_id": guardian_id,
            "guardian_name": guardian_name,
            "is_active": user.is_active,
        }

    async def create_student(
        self,
        first_name: str,
        last_name: str | None,
        email: str,
        password: str,
        birth_date: datetime.date,
        student_class: ClassEnum,
        session: AsyncSession,
        phone_number: str | None = None,
        school_id: uuid.UUID | None = None,
    ) -> dict | None:
        """Create a student atomically; returns None if email already exists."""
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
        school_id: uuid.UUID | None = None,
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

        extra_filters: list[ColumnElement[bool]] = []

        if name:
            extra_filters.append(
                UserProfile.first_name.ilike(f"%{name}%") | UserProfile.last_name.ilike(f"%{name}%")
            )

        if email:
            extra_filters.append(UserProfile.email.ilike(f"%{email}%"))

        if school_id:
            extra_filters.append(StudentProfile.school_id == school_id)

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

        school_names = await self._fetch_school_names(session, school_ids)

        guardian_info = await self._fetch_guardian_info(session, student_ids)

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
        school_id: uuid.UUID | None = None,
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

        if school_id:
            conditions.append(StudentProfile.school_id == school_id)

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
        school_names = await self._fetch_school_names(session, school_ids)
        guardian_info = await self._fetch_guardian_info(session, [student_profile.user_id])
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
        """Update mutable fields on a student."""
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

        user_fields = {"first_name", "last_name", "phone_number"}
        student_fields = {"birth_date", "student_class", "school_id"}

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
        school_names = await self._fetch_school_names(session, school_ids)
        guardian_info = await self._fetch_guardian_info(session, [student_profile.user_id])
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

    async def deactivate_student(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
    ) -> bool:
        """Soft-delete a student; returns False if not found."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(
                StudentProfile.user_id == student_id,
                StudentProfile.deactivated_at.is_(None),
            )
        )

        row = (await session.execute(query)).one_or_none()

        if row is None:
            return False

        user_profile, student_profile = row
        now = datetime.datetime.now(datetime.UTC)
        student_profile.deactivated_at = now
        user_profile.is_active = False
        user_profile.deactivated_at = now

        await session.commit()

        logger.info(
            "Student deactivated",
            extra={**_logger_extra, "student_id": str(student_id)},
        )

        return True

    async def set_student_active_status(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        is_active: bool,
    ) -> bool:
        """Activate or deactivate a student; returns False if not found."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(StudentProfile.user_id == student_id)
        )

        row = (await session.execute(query)).one_or_none()

        if row is None:
            return False

        user_profile, student_profile = row
        now = datetime.datetime.now(datetime.UTC)

        user_profile.is_active = is_active
        user_profile.deactivated_at = None if is_active else now
        student_profile.deactivated_at = None if is_active else now

        await session.commit()

        logger.info(
            "Student active status updated",
            extra={**_logger_extra, "student_id": str(student_id), "is_active": is_active},
        )

        return True

    async def get_summary_metrics(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
    ) -> list[dict]:
        """Return headline task metrics for the student dashboard."""
        total_tasks_q = select(func.count(Task.id)).where(
            Task.student_id == student_id,
            Task.deactivated_at.is_(None),
        )
        total_tasks: int = (await session.execute(total_tasks_q)).scalar() or 0

        done_tasks_q = select(func.count(Task.id)).where(
            Task.student_id == student_id,
            Task.deactivated_at.is_(None),
            Task.task_status == TaskStatusEnum.DONE,
        )
        done_tasks: int = (await session.execute(done_tasks_q)).scalar() or 0

        pending_tasks_q = select(func.count(Task.id)).where(
            Task.student_id == student_id,
            Task.deactivated_at.is_(None),
            Task.task_status == TaskStatusEnum.PENDING,
        )
        pending_tasks: int = (await session.execute(pending_tasks_q)).scalar() or 0

        completion_rate = round((done_tasks / total_tasks) * 100, 1) if total_tasks > 0 else 0.0

        return [
            {"label": "total_tasks", "value": total_tasks},
            {"label": "done_tasks", "value": done_tasks},
            {"label": "pending_tasks", "value": pending_tasks},
            {"label": "completion_rate", "value": completion_rate},
        ]

    async def get_disciplines_progress(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
    ) -> list[dict]:
        """Return task completion grouped by subject."""
        query = (
            select(
                Subject.id,
                Subject.name,
                Subject.color,
                func.count(Task.id).label("total"),
                func.sum(
                    func.cast(Task.task_status == TaskStatusEnum.DONE, type_=func.count().type)
                ).label("done"),
            )
            .select_from(Task)
            .join(Subject, Subject.id == Task.subject_id)
            .where(
                Task.student_id == student_id,
                Task.deactivated_at.is_(None),
            )
            .group_by(Subject.id, Subject.name, Subject.color)
            .order_by(Subject.name)
        )

        rows = (await session.execute(query)).all()

        result = []
        for subject_id, name, color, total, done in rows:
            done = done or 0
            result.append(
                {
                    "subject_id": subject_id,
                    "subject_name": name,
                    "color": color,
                    "total_tasks": total,
                    "done_tasks": done,
                    "completion_rate": round((done / total) * 100, 1) if total > 0 else 0.0,
                }
            )

        return result

    async def get_tasks(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
    ) -> list[dict]:
        """Return all active tasks for a student with subject info."""
        query = (
            select(Task, Subject)
            .join(Subject, Subject.id == Task.subject_id)
            .where(
                Task.student_id == student_id,
                Task.deactivated_at.is_(None),
            )
            .order_by(Task.date)
        )

        rows = (await session.execute(query)).all()

        return [_task_with_subject_to_dict(task, subject) for task, subject in rows]

    async def get_weekly_tasks(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        reference: datetime.date | None = None,
    ) -> list[dict]:
        """Return tasks for the current week (Sunday to Saturday UTC)."""
        week_start, week_end = get_week_bounds(reference)

        query = (
            select(Task, Subject)
            .join(Subject, Subject.id == Task.subject_id)
            .where(
                Task.student_id == student_id,
                Task.deactivated_at.is_(None),
                Task.date >= week_start,
                Task.date <= week_end,
            )
            .order_by(Task.date)
        )

        rows = (await session.execute(query)).all()

        return [_task_with_subject_to_dict(task, subject) for task, subject in rows]

    async def get_well_being(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        date: datetime.date,
    ) -> dict | None:
        """Return a student's well-being record for a specific date."""
        query = select(WellBeing).where(
            WellBeing.student_id == student_id,
            WellBeing.date == date,
        )

        record = (await session.execute(query)).scalar_one_or_none()

        if record is None:
            return None

        return {
            "student_id": str(record.student_id),
            "date": record.date.isoformat(),
            "humor": record.humor.value if record.humor else None,
            "online_activity_minutes": record.online_activity_minutes,
            "sleep_hours": float(record.sleep_hours) if record.sleep_hours is not None else None,
        }

    async def get_well_being_range(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        from_date: datetime.date,
        to_date: datetime.date,
    ) -> list[dict]:
        """Return well-being records in ascending date order."""
        query = (
            select(WellBeing)
            .where(
                WellBeing.student_id == student_id,
                WellBeing.date >= from_date,
                WellBeing.date <= to_date,
            )
            .order_by(WellBeing.date)
        )

        rows = (await session.execute(query)).scalars().all()

        return [
            {
                "student_id": str(r.student_id),
                "date": r.date.isoformat(),
                "humor": r.humor.value if r.humor else None,
                "online_activity_minutes": r.online_activity_minutes,
                "sleep_hours": float(r.sleep_hours) if r.sleep_hours is not None else None,
            }
            for r in rows
        ]

    async def upsert_well_being(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        date: datetime.date,
        humor: str | None = None,
        online_activity_minutes: int | None = None,
        sleep_hours: float | None = None,
    ) -> dict:
        """Atomically create or update a student's well-being record for a date."""
        query = select(WellBeing).where(
            WellBeing.student_id == student_id,
            WellBeing.date == date,
        )

        record = (await session.execute(query)).scalar_one_or_none()

        if record is None:
            record = WellBeing(
                student_id=student_id,
                date=date,
                humor=humor,
                online_activity_minutes=online_activity_minutes,
                sleep_hours=sleep_hours,
            )
            session.add(record)
        else:
            if humor is not None:
                record.humor = humor
            if online_activity_minutes is not None:
                record.online_activity_minutes = online_activity_minutes
            if sleep_hours is not None:
                record.sleep_hours = sleep_hours

        await session.commit()
        await session.refresh(record)

        return {
            "student_id": str(record.student_id),
            "date": record.date.isoformat(),
            "humor": record.humor.value if record.humor else None,
            "online_activity_minutes": record.online_activity_minutes,
            "sleep_hours": float(record.sleep_hours) if record.sleep_hours is not None else None,
        }

    async def sync_calendar_tasks(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        tasks_payload: list[dict],
    ) -> list[dict]:
        """Create or update tasks atomically from a sync payload."""
        now = datetime.datetime.now(datetime.UTC)
        results = []

        for item in tasks_payload:
            task_id = item.get("id")

            if task_id is not None:
                task = (
                    await session.execute(
                        select(Task).where(Task.id == task_id, Task.student_id == student_id)
                    )
                ).scalar_one_or_none()

                if task is None:
                    raise ValueError(f"Task {task_id} not found for this student.")

                if "title" in item:
                    task.title = item["title"]
                if "status" in item:
                    task.task_status = item["status"]
                if "date" in item:
                    task.date = item["date"]
                if "subject_id" in item:
                    task.subject_id = item["subject_id"]
                if item.get("deactivated"):
                    task.deactivated_at = now
            else:
                task = Task(
                    student_id=student_id,
                    title=item["title"],
                    task_status=item.get("status", TaskStatusEnum.PENDING),
                    subject_id=item["subject_id"],
                    date=item["date"],
                )
                session.add(task)

            results.append(task)

        await session.commit()

        task_ids = [t.id for t in results if t.id is not None]
        query = (
            select(Task, Subject)
            .join(Subject, Subject.id == Task.subject_id)
            .where(Task.id.in_(task_ids))
            .order_by(Task.date)
        )

        rows = (await session.execute(query)).all()

        return [_task_with_subject_to_dict(task, subject) for task, subject in rows]

    async def get_calendar_day(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        date: datetime.date,
    ) -> list[dict]:
        """Return all active tasks for a student on a given date."""
        day_start = datetime.datetime(date.year, date.month, date.day, 0, 0, 0, tzinfo=datetime.UTC)
        day_end = datetime.datetime(
            date.year, date.month, date.day, 23, 59, 59, 999999, tzinfo=datetime.UTC
        )

        query = (
            select(Task, Subject)
            .join(Subject, Subject.id == Task.subject_id)
            .where(
                Task.student_id == student_id,
                Task.deactivated_at.is_(None),
                Task.date >= day_start,
                Task.date <= day_end,
            )
            .order_by(Task.date)
        )

        rows = (await session.execute(query)).all()

        return [_task_with_subject_to_dict(task, subject) for task, subject in rows]

    async def upsert_calendar_day(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        date: datetime.date,
        tasks: list[dict],
    ) -> list[dict]:
        """Sync the full task state for a student/date (upsert + soft delete omitted tasks)."""
        now = datetime.datetime.now(datetime.UTC)
        day_start = datetime.datetime(date.year, date.month, date.day, 0, 0, 0, tzinfo=datetime.UTC)
        day_end = datetime.datetime(
            date.year, date.month, date.day, 23, 59, 59, 999999, tzinfo=datetime.UTC
        )

        existing_q = select(Task).where(
            Task.student_id == student_id,
            Task.deactivated_at.is_(None),
            Task.date >= day_start,
            Task.date <= day_end,
        )
        existing_tasks = {t.id: t for t in (await session.execute(existing_q)).scalars().all()}

        incoming_ids: set[int] = set()

        for item in tasks:
            task_id = item.get("id")

            if task_id and task_id in existing_tasks:
                task = existing_tasks[task_id]
                task.title = item.get("title", task.title)
                task.task_status = item.get("status", task.task_status)
                task.subject_id = item.get("subject_id", task.subject_id)
                incoming_ids.add(task_id)
            else:
                task = Task(
                    student_id=student_id,
                    title=item["title"],
                    task_status=item.get("status", TaskStatusEnum.PENDING),
                    subject_id=item["subject_id"],
                    date=datetime.datetime.combine(date, datetime.time(0, 0, tzinfo=datetime.UTC)),
                )
                session.add(task)

        for tid, task in existing_tasks.items():
            if tid not in incoming_ids:
                task.deactivated_at = now

        await session.commit()

        return await self.get_calendar_day(session=session, student_id=student_id, date=date)
