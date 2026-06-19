"""Integration tests for ContentGenerationService."""

import unittest
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from md_backend.models.db_models import Content, Exercise, Subject
from md_backend.services.trail.generation_service import ContentGenerationService
from md_backend.utils.database import AsyncSessionLocal, init_db
from md_backend.utils.settings import settings


class TestContentGenerationService(unittest.IsolatedAsyncioTestCase):
    """Generation service persists exercise bank rows offline."""

    async def asyncSetUp(self):
        await init_db()
        self.service = ContentGenerationService()
        self._old_google_api_key = settings.GOOGLE_API_KEY
        settings.GOOGLE_API_KEY = ""

    async def asyncTearDown(self):
        settings.GOOGLE_API_KEY = self._old_google_api_key

    async def _seed_content(self, session):
        suffix = uuid.uuid4().hex[:8]
        subject = Subject(name=f"Generation {suffix}", slug=f"generation-{suffix}", color="#000")
        session.add(subject)
        await session.flush()
        content = Content(subject_id=subject.id, name=f"Frações {suffix}", description="d")
        session.add(content)
        await session.flush()
        return content

    async def test_generate_raises_when_content_missing(self):
        """Generation requires existing content."""
        async with AsyncSessionLocal() as session:
            with self.assertRaises(LookupError):
                await self.service.generate_for_content(
                    session,
                    content_id=999999,
                    eixo=["frações"],
                    count=2,
                    difficulty=1,
                )

    async def test_generate_persists_exercises_via_fallback(self):
        """Fallback generation creates exercises with exactly one correct option."""
        async with AsyncSessionLocal() as session:
            content = await self._seed_content(session)

            result = await self.service.generate_for_content(
                session,
                content_id=content.id,
                eixo=["frações"],
                count=2,
                difficulty=1,
            )

            self.assertEqual(len(result["created_exercise_ids"]), 2)
            for question in result["questions"]:
                self.assertEqual(
                    sum(1 for option in question["options"] if option["correct"]),
                    1,
                )
            exercises = (
                (
                    await session.execute(
                        select(Exercise)
                        .where(Exercise.id.in_(result["created_exercise_ids"]))
                        .options(selectinload(Exercise.options))
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(exercises), 2)
            for exercise in exercises:
                self.assertEqual(len(exercise.options), 4)
                self.assertEqual(sum(1 for option in exercise.options if option.correct), 1)
