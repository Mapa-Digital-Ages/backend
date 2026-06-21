"""Student progress service for adaptive trails."""

import datetime
import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.db_models import (
    Attempt,
    ItemProgressStatusEnum,
    Option,
    PathStatusEnum,
    PathTransition,
    StudentPathProgress,
    StudentSubPathItemProgress,
    SubPath,
    SubPathItem,
    TypeItemEnum,
)
from md_backend.services.trail.read_service import TrailReadService
from md_backend.services.trail.transition_engine import TransitionRule, pick_next_sub_path


class TrailProgressService:
    """Complete trail items/sub-paths and update student progress."""

    def __init__(self, read_service: TrailReadService | None = None) -> None:
        """Create a progress service."""
        self._read = read_service or TrailReadService()

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

    async def _mark_item_completed(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        path_id: int,
        sub_path_id: int,
        item_id: int,
        now: datetime.datetime,
    ) -> None:
        """Create or update item progress as completed."""
        progress = (
            await session.execute(
                select(StudentSubPathItemProgress).where(
                    StudentSubPathItemProgress.student_id == student_id,
                    StudentSubPathItemProgress.sub_path_item_id == item_id,
                )
            )
        ).scalar_one_or_none()
        if progress is None:
            progress = StudentSubPathItemProgress(
                student_id=student_id,
                path_id=path_id,
                sub_path_id=sub_path_id,
                sub_path_item_id=item_id,
                status=ItemProgressStatusEnum.COMPLETED,
                completed_at=now,
                updated_at=now,
            )
            session.add(progress)
            return

        progress.status = ItemProgressStatusEnum.COMPLETED
        progress.completed_at = progress.completed_at or now
        progress.updated_at = now

    async def _ensure_path_progress(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        path_id: int,
        current_sub_path: int,
    ) -> StudentPathProgress:
        """Fetch or initialize path progress."""
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
                student_id=student_id,
                path_id=path_id,
                current_sub_path=current_sub_path,
                path_status=PathStatusEnum.ON_GOING,
            )
            session.add(progress)
        return progress

    async def _fallback_next_sub_path(
        self, session: AsyncSession, path_id: int, sub_path_id: int
    ) -> int | None:
        """Return the next sub-path by explicit order and then id."""
        current = (
            await session.execute(select(SubPath).where(SubPath.id == sub_path_id))
        ).scalar_one_or_none()
        if current is None:
            return None
        return (
            await session.execute(
                select(SubPath.id)
                .where(
                    SubPath.path_id == path_id,
                    or_(
                        SubPath.order > current.order,
                        and_(SubPath.order == current.order, SubPath.id > sub_path_id),
                    ),
                )
                .order_by(SubPath.order, SubPath.id)
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _resolve_next_sub_path(
        self,
        session: AsyncSession,
        path_id: int,
        sub_path_id: int,
        score: int | None,
    ) -> int | None:
        """Resolve the next sub-path using transition rules and ordered fallback."""
        transitions = (
            (
                await session.execute(
                    select(PathTransition)
                    .where(PathTransition.sub_path_origin_id == sub_path_id)
                    .order_by(PathTransition.id)
                )
            )
            .scalars()
            .all()
        )
        rules = [
            TransitionRule(
                rule_type=transition.rule_type,
                rule_value=transition.rule_value,
                destination_id=transition.sub_path_destination_id,
            )
            for transition in transitions
            if transition.rule_type is not None
        ]
        fallback_next_id = await self._fallback_next_sub_path(
            session=session, path_id=path_id, sub_path_id=sub_path_id
        )
        return pick_next_sub_path(rules, score=score, fallback_next_id=fallback_next_id)

    async def _grade_answers(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        answers: list[dict],
        now: datetime.datetime,
        expected_exercise_id: int | None,
    ) -> tuple[int, int]:
        """Grade answers server-side and record attempts."""
        correct = 0
        total = len(answers)
        for answer in answers:
            option = (
                await session.execute(select(Option).where(Option.id == answer["option_id"]))
            ).scalar_one_or_none()
            exercise_matches = option is not None and option.exercise_id == answer["exercise_id"]
            if option is not None and expected_exercise_id is not None:
                exercise_matches = exercise_matches and option.exercise_id == expected_exercise_id
            is_correct = bool(option is not None and option.correct and exercise_matches)
            if is_correct:
                correct += 1
            session.add(
                Attempt(
                    student_id=student_id,
                    exercise_id=answer["exercise_id"],
                    is_correct=is_correct,
                    time_spent_seconds=0,
                    created_at=now,
                )
            )
        return correct, total

    def _apply_next_progress(
        self,
        progress: StudentPathProgress,
        sub_path_id: int,
        next_id: int | None,
        now: datetime.datetime,
    ) -> None:
        """Update path progress after a completed sub-path."""
        if next_id is None:
            progress.path_status = PathStatusEnum.COMPLETED
            progress.current_sub_path = sub_path_id
            progress.completed_at = progress.completed_at or now
        else:
            progress.path_status = PathStatusEnum.ON_GOING
            progress.current_sub_path = next_id
        progress.updated_at = now

    async def complete(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        path_id: int,
        *,
        sub_path_id: int | None = None,
        item_id: int | None = None,
        answers: list[dict],
    ) -> dict | None:
        """Complete one item or a whole sub-path quiz."""
        now = datetime.datetime.now(datetime.UTC)
        expected_exercise_id: int | None = None
        item: SubPathItem | None = None

        if item_id is not None:
            row = (
                await session.execute(
                    select(SubPathItem, SubPath)
                    .join(SubPath, SubPath.id == SubPathItem.sub_path_id)
                    .where(SubPathItem.id == item_id, SubPath.path_id == path_id)
                )
            ).one_or_none()
            if row is None:
                return None
            selected_item, sub_path = row
            item = selected_item
            sub_path_id = sub_path.id
            if selected_item.type_item == TypeItemEnum.EXERCISE:
                expected_exercise_id = selected_item.exercise_id
        elif sub_path_id is None:
            return None

        correct, total = await self._grade_answers(
            session=session,
            student_id=student_id,
            answers=answers,
            now=now,
            expected_exercise_id=expected_exercise_id,
        )

        assert sub_path_id is not None
        if item is not None:
            await self._mark_item_completed(
                session=session,
                student_id=student_id,
                path_id=path_id,
                sub_path_id=sub_path_id,
                item_id=item.id,
                now=now,
            )

        path_progress = await self._ensure_path_progress(
            session=session,
            student_id=student_id,
            path_id=path_id,
            current_sub_path=sub_path_id,
        )

        sub_path_completed = item is None
        if item is not None:
            playable_item_ids = await self._read.playable_item_ids(session, sub_path_id)
            completed_item_ids = await self._completed_item_ids(
                session=session,
                student_id=student_id,
                path_id=path_id,
                sub_path_id=sub_path_id,
            )
            sub_path_completed = set(playable_item_ids).issubset(completed_item_ids | {item.id})

        if sub_path_completed:
            score = correct if total > 0 else None
            next_id = await self._resolve_next_sub_path(
                session=session, path_id=path_id, sub_path_id=sub_path_id, score=score
            )
            self._apply_next_progress(path_progress, sub_path_id, next_id, now)
        else:
            path_progress.path_status = PathStatusEnum.ON_GOING
            path_progress.current_sub_path = sub_path_id
            path_progress.updated_at = now

        await session.commit()

        if item is None:
            path_status = path_progress.path_status
            return {
                "correct": correct,
                "total": total,
                "passed": total == 0 or correct == total,
                "current_sub_path": path_progress.current_sub_path,
                "path_status": path_status.value if path_status is not None else None,
            }

        detail = await self._read.get_trail_detail(
            session=session, student_id=student_id, path_id=path_id
        )
        if detail is not None:
            detail["last_completion"] = {
                "correct": correct,
                "total": total,
                "passed": total == 0 or correct == total,
            }
        return detail

    async def complete_sub_path(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        path_id: int,
        sub_path_id: int,
        answers: list[dict],
    ) -> dict | None:
        """Complete a full sub-path quiz."""
        return await self.complete(
            session=session,
            student_id=student_id,
            path_id=path_id,
            sub_path_id=sub_path_id,
            answers=answers,
        )

    async def complete_item(
        self,
        session: AsyncSession,
        student_id: uuid.UUID,
        path_id: int,
        item_id: int,
        answers: list[dict],
    ) -> dict | None:
        """Complete one sub-path item."""
        return await self.complete(
            session=session,
            student_id=student_id,
            path_id=path_id,
            item_id=item_id,
            answers=answers,
        )

    async def validate_answer(
        self,
        session: AsyncSession,
        path_id: int,
        sub_path_id: int,
        exercise_id: int,
        option_id: int,
    ) -> dict | None:
        """Validate one selected option for an exercise in a trail quiz."""
        row = (
            await session.execute(
                select(Option)
                .join(SubPathItem, SubPathItem.exercise_id == Option.exercise_id)
                .join(SubPath, SubPath.id == SubPathItem.sub_path_id)
                .where(
                    SubPath.path_id == path_id,
                    SubPath.id == sub_path_id,
                    SubPathItem.type_item == TypeItemEnum.EXERCISE,
                    SubPathItem.exercise_id == exercise_id,
                    Option.id == option_id,
                    Option.exercise_id == exercise_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "exercise_id": exercise_id,
            "option_id": option_id,
            "correct": bool(row.correct),
        }
