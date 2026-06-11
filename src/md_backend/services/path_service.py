"""Path (adaptive trail) service."""

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    Attempt,
    Content,
    Exercise,
    Option,
    Path,
    PathStatusEnum,
    PathTransition,
    Resource,
    ResourceTypeEnum,
    RuleTypeEnum,
    StudentPathProgress,
    SubPath,
    SubPathItem,
    Subject,
    TypeItemEnum,
)


class PathService:
    """Read-only operations for adaptive learning paths."""

    async def _build_sub_steps(
        self,
        session: AsyncSession,
        sub_path_id: int,
        step_status: str,
        subject_payload: dict,
    ) -> list[dict]:
        """Build the UI sub-steps for a sub-path.

        Resource items become individual video/text sub-steps; exercise items are
        collapsed into a single trailing quiz sub-step (no answer key is exposed).
        """
        items = (
            await session.execute(
                select(SubPathItem)
                .where(SubPathItem.sub_path_id == sub_path_id)
                .order_by(SubPathItem.id)
            )
        ).scalars().all()

        sub_steps: list[dict] = []
        quiz_questions: list[dict] = []
        order = 1

        for item in items:
            if item.type_item == TypeItemEnum.EXERCISE:
                exercise = (
                    await session.execute(
                        select(Exercise).where(Exercise.id == item.item_id)
                    )
                ).scalar_one_or_none()
                if exercise is None:
                    continue
                options = (
                    await session.execute(
                        select(Option)
                        .where(Option.exercise_id == exercise.id)
                        .order_by(Option.id)
                    )
                ).scalars().all()
                quiz_questions.append({
                    "id": str(exercise.id),
                    "question": exercise.statement,
                    "options": [{"id": str(o.id), "label": o.text} for o in options],
                    "subject": subject_payload,
                })
            else:
                resource = (
                    await session.execute(
                        select(Resource).where(Resource.id == item.item_id)
                    )
                ).scalar_one_or_none()
                if resource is None:
                    continue
                kind = "video" if resource.type == ResourceTypeEnum.VIDEO else "text"
                sub_steps.append({
                    "id": str(resource.id),
                    "kind": kind,
                    "title": resource.title,
                    "description": "",
                    "order": order,
                    "status": step_status,
                    "questions": [],
                })
                order += 1

        if quiz_questions:
            sub_steps.append({
                "id": f"quiz-{sub_path_id}",
                "kind": "question",
                "title": "Questões",
                "description": "",
                "order": order,
                "status": step_status,
                "questions": quiz_questions,
            })

        return sub_steps

    async def _resolve_next_sub_path(
        self,
        session: AsyncSession,
        path_id: int,
        sub_path_id: int,
        score: int | None,
    ) -> int | None:
        """Pick the next sub-path from PathTransition rules, given the quiz score.

        Conditional rules (bigger/smaller than) are evaluated first in row order;
        the first match wins. Otherwise a STANDARD rule is used; otherwise the next
        sub-path by id; otherwise None (trail completed).
        """
        transitions = (
            await session.execute(
                select(PathTransition)
                .where(PathTransition.sub_path_origin_id == sub_path_id)
                .order_by(PathTransition.id)
            )
        ).scalars().all()

        standard_dest: int | None = None
        for t in transitions:
            if t.rule_type == RuleTypeEnum.STANDARD:
                if standard_dest is None:
                    standard_dest = t.sub_path_destination_id
                continue
            if score is None or t.rule_value is None:
                continue
            if t.rule_type == RuleTypeEnum.BIGGER_THAN and score > t.rule_value:
                return t.sub_path_destination_id
            if t.rule_type == RuleTypeEnum.SMALLER_THAN and score < t.rule_value:
                return t.sub_path_destination_id

        if standard_dest is not None:
            return standard_dest

        next_id = (
            await session.execute(
                select(func.min(SubPath.id)).where(
                    SubPath.path_id == path_id, SubPath.id > sub_path_id
                )
            )
        ).scalar_one_or_none()
        return next_id

    async def complete_sub_path(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        path_id: int,
        sub_path_id: int,
        answers: list[dict],
    ) -> dict:
        """Grade a sub-path quiz, record attempts, and advance the trail.

        ``answers`` may be empty (resource-only sub-path); then no grading happens
        and the standard/next transition is used.
        """
        correct = 0
        total = len(answers)
        now = datetime.datetime.now(datetime.timezone.utc)

        for ans in answers:
            option = (
                await session.execute(
                    select(Option).where(Option.id == ans["option_id"])
                )
            ).scalar_one_or_none()
            is_correct = bool(
                option is not None
                and option.correct
                and option.exercise_id == ans["exercise_id"]
            )
            if is_correct:
                correct += 1
            session.add(Attempt(
                student_id=student_id,
                exercise_id=ans["exercise_id"],
                is_correct=is_correct,
                time_spent_seconds=0,
                created_at=now,
            ))

        score = correct if total > 0 else None
        next_id = await self._resolve_next_sub_path(
            session=session, path_id=path_id, sub_path_id=sub_path_id, score=score
        )

        progress = (
            await session.execute(
                select(StudentPathProgress).where(
                    StudentPathProgress.student_id == student_id,
                    StudentPathProgress.path_id == path_id,
                )
            )
        ).scalar_one_or_none()
        if progress is None:
            progress = StudentPathProgress(
                student_id=student_id, path_id=path_id, current_sub_path=sub_path_id
            )
            session.add(progress)

        if next_id is None:
            progress.path_status = PathStatusEnum.COMPLETED
            progress.current_sub_path = sub_path_id
        else:
            progress.path_status = PathStatusEnum.ON_GOING
            progress.current_sub_path = next_id
        progress.updated_at = now

        await session.commit()

        return {
            "correct": correct,
            "total": total,
            "passed": total == 0 or correct == total,
            "current_sub_path": progress.current_sub_path,
            "path_status": progress.path_status.value if progress.path_status else None,
        }

    async def get_question_flow(
        self, session: AsyncSession, path_id: int, sub_path_id: int
    ) -> dict | None:
        """Return the quiz question flow for one sub-path (no answer key)."""
        subject = (
            await session.execute(
                select(Subject)
                .join(Content, Content.subject_id == Subject.id)
                .join(Path, Path.contents_id == Content.id)
                .where(Path.id == path_id)
            )
        ).scalar_one_or_none()
        if subject is None:
            return None
        subject_payload = {
            "id": str(subject.id),
            "label": subject.name,
            "color": subject.color,
        }

        sub_steps = await self._build_sub_steps(
            session=session,
            sub_path_id=sub_path_id,
            step_status="available",
            subject_payload=subject_payload,
        )
        quiz = next((s for s in sub_steps if s["kind"] == "question"), None)
        questions = quiz["questions"] if quiz else []

        return {
            "assessmentId": str(sub_path_id),
            "trailId": str(path_id),
            "stepId": str(sub_path_id),
            "subStepId": f"quiz-{sub_path_id}",
            "stepTitle": "Questões",
            "questions": questions,
        }

    async def list_trails(
        self, session: AsyncSession, student_id: uuid.UUID
    ) -> list[dict]:
        """List all paths with per-student progress."""
        sub_path_count_sq = (
            select(SubPath.path_id, func.count(SubPath.id).label("total"))
            .group_by(SubPath.path_id)
            .subquery()
        )

        stmt = (
            select(Path, Content, Subject, sub_path_count_sq.c.total)
            .join(Content, Path.contents_id == Content.id)
            .join(Subject, Content.subject_id == Subject.id)
            .outerjoin(sub_path_count_sq, Path.id == sub_path_count_sq.c.path_id)
        )
        rows = (await session.execute(stmt)).all()

        progress_rows = (
            await session.execute(
                select(StudentPathProgress).where(
                    StudentPathProgress.student_id == student_id
                )
            )
        ).scalars().all()

        progress_by_path: dict[int, StudentPathProgress] = {
            p.path_id: p for p in progress_rows
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
                completed = 0
                pct = 0

            result.append({
                "id": str(path.id),
                "name": path.name or content.name,
                "description": path.description or content.description,
                "subject": {
                    "id": str(subject.id),
                    "label": subject.name,
                    "color": subject.color,
                },
                "steps": total,
                "completed": completed,
                "progress": pct,
                "time_estimate": None,
            })

        return result

    async def get_trail_detail(
        self, session: AsyncSession, student_id: uuid.UUID, path_id: int
    ) -> dict | None:
        """Return full trail detail with sub-path statuses for a student."""
        row = (
            await session.execute(
                select(Path, Content, Subject)
                .join(Content, Path.contents_id == Content.id)
                .join(Subject, Content.subject_id == Subject.id)
                .where(Path.id == path_id)
            )
        ).one_or_none()

        if row is None:
            return None

        path, content, subject = row

        subject_payload = {
            "id": str(subject.id),
            "label": subject.name,
            "color": subject.color,
        }

        sub_paths = (
            await session.execute(
                select(SubPath).where(SubPath.path_id == path_id).order_by(SubPath.id)
            )
        ).scalars().all()

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
            if progress is None:
                if order == 1:
                    step_status = "available"
                else:
                    step_status = "locked"
            elif sub_path.id == current_sub_path_id:
                step_status = "available"
                reached_current = True
            elif not reached_current:
                step_status = "completed"
            else:
                step_status = "locked"

            sub_steps = await self._build_sub_steps(
                session=session,
                sub_path_id=sub_path.id,
                step_status=step_status,
                subject_payload=subject_payload,
            )

            steps.append({
                "id": str(sub_path.id),
                "title": f"Etapa {order}",
                "description": None,
                "order": order,
                "status": step_status,
                "sub_steps": sub_steps,
            })

        total = len(steps)
        completed_count = sum(1 for s in steps if s["status"] == "completed")
        pct = round((completed_count / total) * 100) if total > 0 else 0

        return {
            "id": str(path.id),
            "title": path.name or content.name,
            "description": path.description or content.description,
            "subject": {
                "id": str(subject.id),
                "label": subject.name,
                "color": subject.color,
            },
            "progress": pct,
            "completed_steps": completed_count,
            "level_label": None,
            "time_estimate": None,
            "steps": steps,
        }
