"""Student service for student registration."""

import datetime
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    Attempt,
    ClassEnum,
    Content,
    GuardianProfile,
    SchoolProfile,
    StudentContentProgress,
    StudentGuardian,
    StudentProfile,
    Subject,
    Task,
    TaskStatusEnum,
    UserProfile,
    WellBeing,
)
from md_backend.utils.security import hash_password

_TASK_STATUS_TO_FRONTEND = {
    TaskStatusEnum.DONE: "done",
    TaskStatusEnum.PENDING: "pending",
    TaskStatusEnum.ADJUST: "adjust",
}


def get_week_bounds(
    reference: datetime.date | None = None,
) -> tuple[datetime.datetime, datetime.datetime]:
    """Return (week_start, week_end) as UTC-aware datetimes for the current week.

    The week runs from Sunday 00:00:00 UTC to Saturday 23:59:59.999999 UTC,
    matching the calendar convention expected by the frontend.
    """
    if reference is None:
        reference = datetime.datetime.now(datetime.UTC).date()

    # weekday(): Monday=0 … Sunday=6  →  days_since_sunday = (weekday + 1) % 7
    days_since_sunday = (reference.weekday() + 1) % 7
    sunday = reference - datetime.timedelta(days=days_since_sunday)
    saturday = sunday + datetime.timedelta(days=6)

    week_start = datetime.datetime(
        sunday.year, sunday.month, sunday.day, 0, 0, 0, tzinfo=datetime.UTC
    )
    week_end = datetime.datetime(
        saturday.year, saturday.month, saturday.day, 23, 59, 59, 999999, tzinfo=datetime.UTC
    )
    return week_start, week_end


def _task_with_subject_to_dict(task, subject) -> dict:
    """Serialize a (Task, Subject) row to the calendar contract dict."""
    _STATUS_MAP = {
        TaskStatusEnum.DONE: "done",
        TaskStatusEnum.PENDING: "pending",
        TaskStatusEnum.ADJUST: "adjust",
    }
    return {
        "id": task.id,
        "date": task.date.isoformat() if task.date else None,
        "title": task.title,
        "status": _STATUS_MAP.get(task.task_status, "pending") if task.task_status else "pending",
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
        """Create a student atomically across user_profile and student_profile."""
        existing = await session.execute(select(UserProfile).where(UserProfile.email == email))
        if existing.scalar_one_or_none() is not None:
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
        except IntegrityError:
            await session.rollback()
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
        SchoolUser = UserProfile
        q = (
            select(SchoolProfile.user_id, SchoolUser.first_name, SchoolUser.last_name)
            .join(SchoolUser, SchoolUser.id == SchoolProfile.user_id)
            .where(SchoolProfile.user_id.in_(school_ids))
        )
        rows = (await session.execute(q)).all()
        return {row[0]: f"{row[1]} {row[2]}".strip() for row in rows}

    async def _fetch_guardian_info(
        self,
        session: AsyncSession,
        student_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
        """Fetch first active guardian (id, name) per student."""
        if not student_ids:
            return {}
        q = (
            select(
                StudentGuardian.student_id,
                GuardianProfile.user_id,
                UserProfile.first_name,
                UserProfile.last_name,
            )
            .select_from(StudentGuardian)
            .join(GuardianProfile, GuardianProfile.user_id == StudentGuardian.guardian_id)
            .join(UserProfile, UserProfile.id == GuardianProfile.user_id)
            .where(
                StudentGuardian.student_id.in_(student_ids),
                StudentGuardian.deactivated_at.is_(None),
            )
        )
        rows = (await session.execute(q)).all()
        result: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
        for student_id, guardian_id, first_name, last_name in rows:
            if student_id not in result:
                result[student_id] = (guardian_id, f"{first_name} {last_name}".strip())
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

        count_q = (
            select(func.count(UserProfile.id))
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(*base_conditions, *extra_filters)
        )
        total: int = (await session.execute(count_q)).scalar() or 0

        items_q = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(*base_conditions, *extra_filters)
            .order_by(
                func.lower(UserProfile.first_name),
                func.lower(UserProfile.last_name),
                UserProfile.id,
            )
            .offset((page - 1) * size)
            .limit(size)
        )
        rows = (await session.execute(items_q)).all()

        school_ids = {sp.school_id for _, sp in rows if sp.school_id is not None}
        student_ids = [sp.user_id for _, sp in rows]
        school_names = await self._fetch_school_names(session, school_ids)
        guardian_info = await self._fetch_guardian_info(session, student_ids)

        items = []
        for user, student in rows:
            g = guardian_info.get(student.user_id)
            items.append(
                self._to_dict(
                    user,
                    student,
                    school_name=school_names.get(student.school_id) if student.school_id else None,
                    guardian_id=str(g[0]) if g else None,
                    guardian_name=g[1] if g else None,
                )
            )

        total_pages = (total + size - 1) // size if size > 0 else 0

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
        """Return the total count of active students, optionally filtered by name."""
        conditions = [
            UserProfile.is_active.is_(True),
            StudentProfile.deactivated_at.is_(None),
        ]
        if name:
            conditions.append(
                UserProfile.first_name.ilike(f"%{name}%") | UserProfile.last_name.ilike(f"%{name}%")
            )
        q = (
            select(func.count(UserProfile.id))
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(*conditions)
        )
        return (await session.execute(q)).scalar() or 0

    async def get_student_by_id(self, session: AsyncSession, student_id: uuid.UUID) -> dict | None:
        """Get a student by user_id."""
        query = (
            select(UserProfile, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == UserProfile.id)
            .where(
                StudentProfile.user_id == student_id,
                UserProfile.is_active.is_(True),
                StudentProfile.deactivated_at.is_(None),
            )
        )

        result = await session.execute(query)
        row = result.one_or_none()

        if row is None:
            return None

        user_profile, student_profile = row
        school_ids = {student_profile.school_id} if student_profile.school_id else set()
        school_names = await self._fetch_school_names(session, school_ids)
        guardian_info = await self._fetch_guardian_info(session, [student_profile.user_id])
        g = guardian_info.get(student_profile.user_id)
        return self._to_dict(
            user_profile,
            student_profile,
            school_name=(
                school_names.get(student_profile.school_id) if student_profile.school_id else None
            ),
            guardian_id=str(g[0]) if g else None,
            guardian_name=g[1] if g else None,
        )

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
            .where(
                StudentProfile.user_id == student_id,
                UserProfile.is_active.is_(True),
                StudentProfile.deactivated_at.is_(None),
            )
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
        g = guardian_info.get(student_profile.user_id)
        return self._to_dict(
            user_profile,
            student_profile,
            school_name=(
                school_names.get(student_profile.school_id) if student_profile.school_id else None
            ),
            guardian_id=str(g[0]) if g else None,
            guardian_name=g[1] if g else None,
        )

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

        await session.execute(
            update(StudentGuardian)
            .where(
                StudentGuardian.student_id == student_id,
                StudentGuardian.deactivated_at.is_(None),
            )
            .values(deactivated_at=now)
        )

        await session.commit()
        return True

    async def get_summary_metrics(self, session: AsyncSession, student_id: uuid.UUID) -> list[dict]:
        """Headline metrics for the student dashboard."""
        completed_tasks_q = select(func.count(Task.id)).where(
            Task.student_id == student_id,
            Task.task_status == TaskStatusEnum.DONE,
            Task.deactivated_at.is_(None),
        )
        attempts_q = select(func.count(Attempt.id)).where(Attempt.student_id == student_id)
        mood_days_q = select(func.count(WellBeing.date)).where(WellBeing.student_id == student_id)

        completed_tasks = (await session.execute(completed_tasks_q)).scalar() or 0
        attempts = (await session.execute(attempts_q)).scalar() or 0
        mood_days = (await session.execute(mood_days_q)).scalar() or 0

        return [
            {"id": "completed-tasks", "title": "Tarefas Concluídas", "value": completed_tasks},
            {"id": "activities", "title": "Atividades Feitas", "value": attempts},
            {"id": "mood-days", "title": "Dias Registrados", "value": mood_days},
        ]

    async def get_disciplines_progress(
        self, session: AsyncSession, student_id: uuid.UUID
    ) -> list[dict]:
        """Average mastery (0-100) per subject for the given student."""
        query = (
            select(
                Subject.id,
                Subject.name,
                func.avg(StudentContentProgress.mastery_level).label("avg_mastery"),
            )
            .join(Content, Content.subject_id == Subject.id)
            .join(StudentContentProgress, StudentContentProgress.content_id == Content.id)
            .where(
                StudentContentProgress.student_id == student_id,
                StudentContentProgress.deactivated_at.is_(None),
            )
            .group_by(Subject.id, Subject.name)
            .order_by(Subject.name)
        )

        rows = (await session.execute(query)).all()
        return [self._discipline_to_dict(row) for row in rows]

    async def get_tasks(self, session: AsyncSession, student_id: uuid.UUID) -> list[dict]:
        """All non-deactivated tasks for the student, newest first."""
        query = (
            select(Task)
            .where(Task.student_id == student_id, Task.deactivated_at.is_(None))
            .order_by(Task.date.desc())
        )
        tasks = (await session.execute(query)).scalars().all()
        return [self._task_to_dict(task) for task in tasks]

    async def get_weekly_tasks(self, session: AsyncSession, student_id: uuid.UUID) -> list[dict]:
        """Return non-deactivated tasks for the current week, joined with subject.

        Week boundaries are computed server-side (Sunday → Saturday, UTC).
        """
        week_start, week_end = get_week_bounds()

        query = (
            select(Task, Subject)
            .join(Subject, Subject.id == Task.subject_id)
            .where(
                Task.student_id == student_id,
                Task.deactivated_at.is_(None),
                Task.date >= week_start,
                Task.date <= week_end,
            )
            .order_by(Task.date.asc())
        )

        rows = (await session.execute(query)).all()
        return [_task_with_subject_to_dict(task, subject) for task, subject in rows]

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

    def _to_dict(
        self,
        user_profile: UserProfile,
        student_profile: StudentProfile,
        school_name: str | None = None,
        guardian_name: str | None = None,
        guardian_id: str | None = None,
    ) -> dict:
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
            "school_id": str(student_profile.school_id) if student_profile.school_id else None,
            "school_name": school_name,
            "guardian_id": guardian_id,
            "guardian_name": guardian_name,
            "is_active": user_profile.is_active,
            "created_at": user_profile.created_at.isoformat() if user_profile.created_at else None,
        }

    def _discipline_to_dict(self, row) -> dict:
        """Map a (subject_id, name, avg_mastery) row to a discipline progress dict."""
        subject_id, name, avg_mastery = row
        return {
            "subjectId": str(subject_id),
            "subjectLabel": name,
            "progress": int(round(float(avg_mastery or 0) * 100)),
        }

    def _task_to_dict(self, task: Task) -> dict:
        """Map a Task row to the response dict expected by the dashboard."""
        task_status = task.task_status
        return {
            "id": str(task.id),
            "title": task.title,
            "date": task.date.isoformat() if task.date else None,
            "status": (
                _TASK_STATUS_TO_FRONTEND.get(task_status, "pending")
                if task_status is not None
                else "pending"
            ),
            "subject": {"label": ""},
        }

    async def sync_calendar_tasks(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        tasks_payload: list[dict],
    ) -> list[dict]:
        """Atomic upsert for daily calendar tasks."""
        persisted_tasks = []

        async with session.begin_nested():
            for item in tasks_payload:
                subject_id = item["subject"]["id"]

                subject_exists = await session.execute(
                    select(Subject).where(Subject.id == subject_id)
                )

                if subject_exists.scalar_one_or_none() is None:
                    raise ValueError(f"Invalid subject_id: {subject_id}")

                incoming_id = item["id"]

                if isinstance(incoming_id, int):
                    result = await session.execute(
                        select(Task).where(
                            Task.id == incoming_id,
                            Task.student_id == student_id,
                            Task.deactivated_at.is_(None),
                        )
                    )

                    task = result.scalar_one_or_none()

                    if task is None:
                        raise ValueError(f"Task not found: {incoming_id}")

                    task.title = item["title"]
                    task.task_status = item["task_status"]
                    task.subject_id = subject_id
                    task.date = item["date"]

                else:
                    task = Task(
                        student_id=student_id,
                        title=item["title"],
                        task_status=item["task_status"],
                        subject_id=subject_id,
                        date=item["date"],
                    )
                    session.add(task)
                    await session.flush()

                persisted_tasks.append(task)

        return [self._task_to_dict(task) for task in persisted_tasks]
