"""Integration tests for TrailProgressService."""

import unittest
import uuid
from unittest.mock import MagicMock

import tests.keys_test  # noqa: F401
from sqlalchemy import select

from md_backend.models.db_models import (
    Content,
    DifficultyEnum,
    Exercise,
    Option,
    Path,
    PathStatusEnum,
    StudentPathProgress,
    Subject,
    SubPath,
    SubPathItem,
    TypeItemEnum,
)
from md_backend.services.trail.progress_service import TrailProgressService
from md_backend.services.trail.read_service import TrailReadService
from md_backend.utils.database import AsyncSessionLocal, init_db


class TestTrailProgressPosition(unittest.TestCase):
    def test_retake_does_not_move_completed_or_more_advanced_progress_backwards(self):
        completed = MagicMock(
            path_status=PathStatusEnum.COMPLETED,
            current_sub_path=20,
        )
        advanced = MagicMock(
            path_status=PathStatusEnum.ON_GOING,
            current_sub_path=20,
        )
        current = MagicMock(
            path_status=PathStatusEnum.ON_GOING,
            current_sub_path=10,
        )

        self.assertFalse(TrailProgressService._can_change_path_position(completed, 10))
        self.assertFalse(TrailProgressService._can_change_path_position(advanced, 10))
        self.assertTrue(TrailProgressService._can_change_path_position(current, 10))


class TestTrailProgressService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()

    async def test_completing_last_sub_path_sets_completed_at(self):
        student_id = uuid.uuid4()
        suffix = uuid.uuid4().hex[:8]

        async with AsyncSessionLocal() as session:
            subject = Subject(name=f"Subject {suffix}", slug=f"subject-{suffix}", color="#000")
            session.add(subject)
            await session.flush()
            content = Content(subject_id=subject.id, name=f"Content {suffix}", description="d")
            session.add(content)
            await session.flush()
            path = Path(content_id=content.id, name=f"Path {suffix}", description="d")
            session.add(path)
            await session.flush()
            sub_path = SubPath(path_id=path.id)
            session.add(sub_path)
            await session.flush()

            result = await TrailProgressService().complete(
                session=session,
                student_id=student_id,
                path_id=path.id,
                sub_path_id=sub_path.id,
                answers=[],
            )

            self.assertIsNotNone(result)
            self.assertEqual(result["path_status"], "completed")
            progress = (
                await session.execute(
                    select(StudentPathProgress).where(
                        StudentPathProgress.student_id == student_id,
                        StudentPathProgress.path_id == path.id,
                    )
                )
            ).scalar_one()
            self.assertIsNotNone(progress.completed_at)

    async def test_completing_one_question_group_keeps_sibling_available(self):
        student_id = uuid.uuid4()
        suffix = uuid.uuid4().hex[:8]

        async with AsyncSessionLocal() as session:
            subject = Subject(name=f"Grouped Subject {suffix}", slug=f"grouped-{suffix}")
            session.add(subject)
            await session.flush()
            content = Content(subject_id=subject.id, name=f"Grouped Content {suffix}")
            session.add(content)
            await session.flush()
            path = Path(content_id=content.id, name=f"Grouped Path {suffix}")
            session.add(path)
            await session.flush()
            sub_path = SubPath(path_id=path.id, title="Etapa agrupada")
            session.add(sub_path)
            await session.flush()

            first_exercise = Exercise(
                content_id=content.id,
                statement="Questão 1",
                difficulty=DifficultyEnum.EASY,
            )
            second_exercise = Exercise(
                content_id=content.id,
                statement="Questão 2",
                difficulty=DifficultyEnum.EASY,
            )
            session.add_all([first_exercise, second_exercise])
            await session.flush()
            first_option = Option(exercise_id=first_exercise.id, text="Certa", correct=True)
            second_option = Option(exercise_id=second_exercise.id, text="Certa", correct=True)
            session.add_all([first_option, second_option])
            await session.flush()
            first_item = SubPathItem(
                sub_path_id=sub_path.id,
                type_item=TypeItemEnum.EXERCISE,
                exercise_id=first_exercise.id,
                group_key="first",
                title="Primeiro questionário",
                order=1,
            )
            second_item = SubPathItem(
                sub_path_id=sub_path.id,
                type_item=TypeItemEnum.EXERCISE,
                exercise_id=second_exercise.id,
                group_key="second",
                title="Segundo questionário",
                order=2,
            )
            session.add_all([first_item, second_item])
            await session.flush()

            first_sub_step_id = f"quiz-{sub_path.id}-first"
            flow = await TrailReadService().get_question_flow(
                session=session,
                path_id=path.id,
                sub_path_id=sub_path.id,
                sub_step_id=first_sub_step_id,
                student_id=student_id,
            )
            self.assertEqual(flow["subStepId"], first_sub_step_id)
            self.assertEqual(flow["itemIds"], [str(first_item.id)])

            detail = await TrailProgressService().complete(
                session=session,
                student_id=student_id,
                path_id=path.id,
                sub_path_id=sub_path.id,
                item_ids=[first_item.id],
                answers=[
                    {
                        "exercise_id": first_exercise.id,
                        "option_id": first_option.id,
                    }
                ],
            )

            self.assertEqual(detail["path_status"], PathStatusEnum.ON_GOING.value)
            self.assertEqual(detail["current_sub_path"], sub_path.id)
            statuses = {
                sub_step["id"]: sub_step["status"] for sub_step in detail["steps"][0]["sub_steps"]
            }
            self.assertEqual(statuses[first_sub_step_id], "completed")
            self.assertEqual(statuses[f"quiz-{sub_path.id}-second"], "available")
