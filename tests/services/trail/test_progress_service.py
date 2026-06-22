"""Integration tests for TrailProgressService."""

import unittest
import uuid

import tests.keys_test  # noqa: F401
from sqlalchemy import select

from md_backend.models.db_models import Content, Path, StudentPathProgress, Subject, SubPath
from md_backend.services.trail.progress_service import TrailProgressService
from md_backend.utils.database import AsyncSessionLocal, init_db


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
