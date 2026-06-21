"""Read and serialization service for adaptive trails."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from md_backend.models.db_models import (
    Content,
    Exercise,
    ItemProgressStatusEnum,
    Option,
    Path,
    PathStatusEnum,
    ResourceTypeEnum,
    StudentPathProgress,
    StudentSubPathItemProgress,
    Subject,
    SubPath,
    SubPathItem,
    TypeItemEnum,
)


class TrailReadService:
    """Read-only operations and response serialization for adaptive trails."""

    def _subject_payload(self, subject: Subject) -> dict:
        """Serialize a subject for trail API responses."""
        return {
            "id": subject.slug or str(subject.id),
            "label": subject.name,
            "color": subject.color,
        }

    async def _completed_item_ids(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        path_id: int,
        sub_path_id: int,
    ) -> set[int]:
        """Return completed item ids for a student within one sub-path."""
        rows = (
            (
                await session.execute(
                    select(StudentSubPathItemProgress.sub_path_item_id).where(
                        StudentSubPathItemProgress.student_id == student_id,
                        StudentSubPathItemProgress.path_id == path_id,
                        StudentSubPathItemProgress.sub_path_id == sub_path_id,
                        StudentSubPathItemProgress.status == ItemProgressStatusEnum.COMPLETED,
                    )
                )
            )
            .scalars()
            .all()
        )
        return set(rows)

    def _apply_item_statuses(
        self,
        sub_steps: list[dict],
        step_status: str,
        completed_item_ids: set[int],
    ) -> list[dict]:
        """Apply item-level statuses while preserving the current step lock state."""
        if step_status != "available":
            return [{**sub_step, "status": step_status} for sub_step in sub_steps]

        previous_completed = True
        result: list[dict] = []
        for sub_step in sub_steps:
            item_ids = [int(i) for i in sub_step.get("item_ids", [sub_step["item_id"]])]
            is_completed = all(item_id in completed_item_ids for item_id in item_ids)
            if is_completed:
                status = "completed"
            elif previous_completed:
                status = "available"
            else:
                status = "locked"
            result.append({**sub_step, "status": status})
            previous_completed = status == "completed"
        return result

    async def _items_for_sub_path(
        self, session: AsyncSession, sub_path_id: int
    ) -> list[SubPathItem]:
        """Load sub-path items with their target content."""
        return list(
            (
                await session.execute(
                    select(SubPathItem)
                    .where(SubPathItem.sub_path_id == sub_path_id)
                    .order_by(SubPathItem.order, SubPathItem.id)
                    .options(
                        selectinload(SubPathItem.resource),
                        selectinload(SubPathItem.exercise).selectinload(Exercise.options),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def _build_sub_steps(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        path_id: int,
        sub_path_id: int,
        step_status: str,
        subject_payload: dict,
    ) -> list[dict]:
        """Build the UI sub-steps for a sub-path without exposing answer keys."""
        items = await self._items_for_sub_path(session=session, sub_path_id=sub_path_id)

        sub_steps: list[dict] = []
        grouped_items: dict[str, list[SubPathItem]] = {}
        group_order: list[str] = []
        order = 1

        for item in items:
            if item.type_item == TypeItemEnum.EXERCISE and not item.group_key:
                group_key = f"legacy-quiz-{sub_path_id}"
            else:
                group_key = item.group_key or f"item-{item.id}"
            if group_key not in grouped_items:
                grouped_items[group_key] = []
                group_order.append(group_key)
            grouped_items[group_key].append(item)

        for group_key in group_order:
            group_items = grouped_items[group_key]
            first_item = group_items[0]

            if first_item.type_item == TypeItemEnum.EXERCISE:
                quiz_questions: list[dict] = []
                quiz_item_ids: list[int] = []
                for item in group_items:
                    if item.type_item != TypeItemEnum.EXERCISE:
                        continue
                    exercise = item.exercise
                    if exercise is None or not exercise.options:
                        continue
                    quiz_questions.append(
                        {
                            "id": str(exercise.id),
                            "question": exercise.statement,
                            "options": [
                                {"id": str(option.id), "label": option.text}
                                for option in exercise.options
                            ],
                            "subject": subject_payload,
                        }
                    )
                    quiz_item_ids.append(item.id)

                if quiz_questions:
                    quiz_id = (
                        f"quiz-{sub_path_id}"
                        if group_key.startswith("legacy-quiz-")
                        else f"quiz-{sub_path_id}-{group_key}"
                    )
                    sub_steps.append(
                        {
                            "id": quiz_id,
                            "item_id": str(quiz_item_ids[0]),
                            "item_ids": [str(item_id) for item_id in quiz_item_ids],
                            "kind": "question",
                            "title": first_item.title or "Questões",
                            "description": first_item.description or "",
                            "order": order,
                            "status": "locked",
                            "questions": quiz_questions,
                        }
                    )
                    order += 1
                continue

            resource = first_item.resource
            if resource is None:
                continue
            kind = "video" if resource.type == ResourceTypeEnum.VIDEO else "text"
            sub_steps.append(
                {
                    "id": str(resource.id),
                    "item_id": str(first_item.id),
                    "item_ids": [str(first_item.id)],
                    "kind": kind,
                    "title": first_item.title or resource.title,
                    "description": first_item.description or "",
                    "order": order,
                    "status": "locked",
                    "questions": [],
                }
            )
            order += 1

        if not sub_steps:
            quiz_questions: list[dict] = []
            quiz_item_ids: list[int] = []
            for item in items:
                if item.type_item != TypeItemEnum.EXERCISE:
                    continue
                exercise = item.exercise
                if exercise is None or not exercise.options:
                    continue
                quiz_questions.append(
                    {
                        "id": str(exercise.id),
                        "question": exercise.statement,
                        "options": [
                            {"id": str(option.id), "label": option.text}
                            for option in exercise.options
                        ],
                        "subject": subject_payload,
                    }
                )
                quiz_item_ids.append(item.id)

            if quiz_questions:
                sub_steps.append(
                    {
                        "id": f"quiz-{sub_path_id}",
                        "item_id": str(quiz_item_ids[0]),
                        "item_ids": [str(item_id) for item_id in quiz_item_ids],
                        "kind": "question",
                        "title": "Questões",
                        "description": "",
                        "order": order,
                        "status": "locked",
                        "questions": quiz_questions,
                    }
                )

        completed_item_ids: set[int] = set()
        if sub_steps and step_status == "available":
            completed_item_ids = await self._completed_item_ids(
                session=session,
                student_id=student_id,
                path_id=path_id,
                sub_path_id=sub_path_id,
            )
        return self._apply_item_statuses(
            sub_steps=sub_steps,
            step_status=step_status,
            completed_item_ids=completed_item_ids,
        )

    async def playable_item_ids(self, session: AsyncSession, sub_path_id: int) -> list[int]:
        """Return item ids that can participate in progress."""
        items = await self._items_for_sub_path(session=session, sub_path_id=sub_path_id)
        result: list[int] = []
        for item in items:
            if item.type_item == TypeItemEnum.RESOURCE:
                result.append(item.id)
                continue
            if item.exercise is not None and item.exercise.options:
                result.append(item.id)
        return result

    async def get_question_flow(
        self, session: AsyncSession, path_id: int, sub_path_id: int
    ) -> dict | None:
        """Return the quiz question flow for one sub-path."""
        subject = (
            await session.execute(
                select(Subject)
                .join(Content, Content.subject_id == Subject.id)
                .join(Path, Path.content_id == Content.id)
                .where(Path.id == path_id)
            )
        ).scalar_one_or_none()
        if subject is None:
            return None
        subject_payload = self._subject_payload(subject)

        sub_steps = await self._build_sub_steps(
            session=session,
            student_id=uuid.UUID(int=0),
            path_id=path_id,
            sub_path_id=sub_path_id,
            step_status="available",
            subject_payload=subject_payload,
        )
        quiz = next((step for step in sub_steps if step["kind"] == "question"), None)
        questions = quiz["questions"] if quiz else []

        return {
            "assessmentId": str(sub_path_id),
            "trailId": str(path_id),
            "stepId": str(sub_path_id),
            "subStepId": f"quiz-{sub_path_id}",
            "stepTitle": "Questões",
            "questions": questions,
        }

    async def list_trails(self, session: AsyncSession, student_id: uuid.UUID) -> list[dict]:
        """List all paths with per-student progress."""
        sub_path_count_sq = (
            select(SubPath.path_id, func.count(SubPath.id).label("total"))
            .group_by(SubPath.path_id)
            .subquery()
        )

        has_options = (
            select(Option.id).where(Option.exercise_id == SubPathItem.exercise_id).exists()
        )
        playable = (
            select(SubPathItem.id)
            .join(SubPath, SubPath.id == SubPathItem.sub_path_id)
            .where(
                SubPath.path_id == Path.id,
                or_(SubPathItem.type_item == TypeItemEnum.RESOURCE, has_options),
            )
            .exists()
        )

        stmt = (
            select(Path, Content, Subject, sub_path_count_sq.c.total)
            .join(Content, Path.content_id == Content.id)
            .join(Subject, Content.subject_id == Subject.id)
            .outerjoin(sub_path_count_sq, Path.id == sub_path_count_sq.c.path_id)
            .where(playable)
        )
        rows = (await session.execute(stmt)).all()

        progress_rows = (
            (
                await session.execute(
                    select(StudentPathProgress).where(StudentPathProgress.student_id == student_id)
                )
            )
            .scalars()
            .all()
        )
        progress_by_path: dict[int, StudentPathProgress] = {
            progress.path_id: progress for progress in progress_rows
        }

        result = []
        for path, content, subject, total_steps in rows:
            total = total_steps or 0
            progress_record = progress_by_path.get(path.id)

            if progress_record is None:
                completed = 0
                pct = 0
            elif progress_record.path_status == PathStatusEnum.COMPLETED:
                completed = total
                pct = 100
            else:
                completed = (
                    await session.execute(
                        select(func.count(SubPath.id)).where(
                            SubPath.path_id == path.id,
                            SubPath.id < progress_record.current_sub_path,
                        )
                    )
                ).scalar_one() or 0
                pct = round((completed / total) * 100) if total > 0 else 0

            result.append(
                {
                    "id": str(path.id),
                    "name": path.name or content.name,
                    "description": path.description or content.description,
                    "subject": self._subject_payload(subject),
                    "steps": total,
                    "completed": completed,
                    "progress": pct,
                    "time_estimate": None,
                }
            )

        return result

    async def get_trail_detail(
        self, session: AsyncSession, student_id: uuid.UUID, path_id: int
    ) -> dict | None:
        """Return full trail detail with sub-path statuses for a student."""
        row = (
            await session.execute(
                select(Path, Content, Subject)
                .join(Content, Path.content_id == Content.id)
                .join(Subject, Content.subject_id == Subject.id)
                .where(Path.id == path_id)
            )
        ).one_or_none()

        if row is None:
            return None

        path, content, subject = row
        subject_payload = self._subject_payload(subject)

        sub_paths = (
            (
                await session.execute(
                    select(SubPath)
                    .where(SubPath.path_id == path_id)
                    .order_by(SubPath.order, SubPath.id)
                )
            )
            .scalars()
            .all()
        )

        progress = (
            await session.execute(
                select(StudentPathProgress).where(
                    StudentPathProgress.student_id == student_id,
                    StudentPathProgress.path_id == path_id,
                )
            )
        ).scalar_one_or_none()

        current_sub_path_id: int | None = (
            progress.current_sub_path if progress is not None else None
        )

        steps = []
        reached_current = False
        for order, sub_path in enumerate(sub_paths, start=1):
            if progress is not None and progress.path_status == PathStatusEnum.COMPLETED:
                step_status = "completed"
            elif progress is None:
                step_status = "available" if order == 1 else "locked"
            elif sub_path.id == current_sub_path_id:
                step_status = "available"
                reached_current = True
            elif not reached_current:
                step_status = "completed"
            else:
                step_status = "locked"

            sub_steps = await self._build_sub_steps(
                session=session,
                student_id=student_id,
                path_id=path_id,
                sub_path_id=sub_path.id,
                step_status=step_status,
                subject_payload=subject_payload,
            )

            steps.append(
                {
                    "id": str(sub_path.id),
                    "title": sub_path.title or f"Etapa {order}",
                    "description": sub_path.description,
                    "order": order,
                    "status": step_status,
                    "sub_steps": sub_steps,
                }
            )

        total = len(steps)
        completed_count = sum(1 for step in steps if step["status"] == "completed")
        pct = round((completed_count / total) * 100) if total > 0 else 0

        return {
            "id": str(path.id),
            "title": path.name or content.name,
            "description": path.description or content.description,
            "subject": subject_payload,
            "progress": pct,
            "completed_steps": completed_count,
            "level_label": None,
            "time_estimate": None,
            "steps": steps,
        }

    async def list_subject_trail_details(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        subject_id: str,
    ) -> list[dict] | None:
        """Return all playable trail details for one subject id or slug."""
        subject_filter = Subject.slug == subject_id
        if subject_id.isdigit():
            subject_filter = or_(Subject.id == int(subject_id), Subject.slug == subject_id)

        subject = (
            await session.execute(select(Subject).where(subject_filter))
        ).scalar_one_or_none()
        if subject is None:
            return None

        trails = await self.list_trails(session=session, student_id=student_id)
        subject_payload = self._subject_payload(subject)
        subject_trail_ids = [
            int(trail["id"]) for trail in trails if trail["subject"]["id"] == subject_payload["id"]
        ]

        details = []
        for path_id in subject_trail_ids:
            detail = await self.get_trail_detail(
                session=session,
                student_id=student_id,
                path_id=path_id,
            )
            if detail is not None:
                details.append(detail)
        return details
