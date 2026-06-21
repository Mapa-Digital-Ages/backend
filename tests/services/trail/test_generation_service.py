"""Integration tests for ContentGenerationService."""

import unittest
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from md_backend.models.db_models import Content, DifficultyEnum, Exercise, Subject
from md_backend.services.trail.generation_service import (
    ContentGenerationService,
    _LlmOption,
    _LlmQuestion,
)
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

    def test_build_llm_uses_configured_model_and_caps_retries(self):
        """The LLM client honors the configured model and a low retry cap."""
        old_model = settings.GEMINI_MODEL
        old_retries = settings.LLM_GENERATION_MAX_RETRIES
        old_key = settings.GOOGLE_API_KEY
        settings.GEMINI_MODEL = "gemini-2.5-flash"
        settings.LLM_GENERATION_MAX_RETRIES = 1
        settings.GOOGLE_API_KEY = "test-key"
        try:
            llm = self.service._build_llm()
            self.assertEqual(llm.model, "gemini-2.5-flash")
            self.assertEqual(llm.max_retries, 1)
        finally:
            settings.GEMINI_MODEL = old_model
            settings.LLM_GENERATION_MAX_RETRIES = old_retries
            settings.GOOGLE_API_KEY = old_key

    async def test_fallback_batch_returns_distinct_questions(self):
        """Batch fallback generates the requested count, all distinct, 1 correct each."""
        questions = await self.service._generate_batch(
            materia="Matemática",
            conteudo="Frações",
            eixo=["frações"],
            count=3,
            difficulty=1,
        )
        self.assertEqual(len(questions), 3)
        statements = [question.statement for question in questions]
        self.assertEqual(len(set(statements)), 3)
        for question in questions:
            self.assertEqual(sum(1 for option in question.options if option.correct), 1)

    async def test_stored_difficulty_matches_requested_not_llm(self):
        """Exercise difficulty follows the requested step level, not the LLM's claim."""

        async def fake_batch(*_args, **_kwargs):
            return [
                _LlmQuestion(
                    statement="Q",
                    difficulty=3,
                    options=[
                        _LlmOption(text="a", correct=True),
                        _LlmOption(text="b", correct=False),
                        _LlmOption(text="c", correct=False),
                        _LlmOption(text="d", correct=False),
                    ],
                )
            ]

        self.service._generate_batch = fake_batch
        async with AsyncSessionLocal() as session:
            content = await self._seed_content(session)
            result = await self.service.generate_for_content(
                session,
                content_id=content.id,
                eixo=["x"],
                count=1,
                difficulty=1,
            )
            exercise = (
                await session.execute(
                    select(Exercise).where(Exercise.id == result["created_exercise_ids"][0])
                )
            ).scalar_one()
            self.assertEqual(exercise.difficulty, DifficultyEnum.EASY)

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
