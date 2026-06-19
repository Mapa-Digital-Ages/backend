"""Offline AI question generation for trail authoring."""

from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from md_backend.models.api_models import GeneratedOption, GeneratedQuestion
from md_backend.models.db_models import Content, DifficultyEnum, Exercise, Option
from md_backend.utils.logger import get_logger
from md_backend.utils.settings import settings

logger = get_logger(__name__)

_SYSTEM_PROMPT = """Você é um gerador de questões objetivas em português para alunos do
5º ao 9º ano. Gere UMA pergunta objetiva que teste DIRETAMENTE o eixo informado, com
exatamente 4 alternativas e UMA correta. Respeite a dificuldade: 1=fácil, 2=médio,
3=difícil. Não inclua letras como "a)" no texto das alternativas."""
_HUMAN_PROMPT = "eixo: {eixo}\nconteudo: {conteudo}\nmateria: {materia}\ndificuldade: {dificuldade}"
_prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM_PROMPT), ("human", _HUMAN_PROMPT)])
_DIFFICULTY_MAP = {1: DifficultyEnum.EASY, 2: DifficultyEnum.MEDIUM, 3: DifficultyEnum.HARD}


class _LlmOption(BaseModel):
    """Structured output option returned by the LLM."""

    text: str
    correct: bool


class _LlmQuestion(BaseModel):
    """Structured output question returned by the LLM."""

    statement: str = Field(..., description="Enunciado da pergunta objetiva.")
    difficulty: int = Field(..., ge=1, le=3)
    options: list[_LlmOption] = Field(..., min_length=4, max_length=4)


class ContentGenerationService:
    """Generate and persist Exercise/Option rows for existing content."""

    async def generate_for_content(
        self,
        session: AsyncSession,
        content_id: int,
        *,
        eixo: list[str],
        count: int,
        difficulty: int,
    ) -> dict:
        """Generate questions for content and persist the answer key server-side."""
        content = (
            await session.execute(
                select(Content)
                .where(Content.id == content_id)
                .options(selectinload(Content.subject))
            )
        ).scalar_one_or_none()
        if content is None:
            raise LookupError("content not found")

        materia = content.subject.name if content.subject is not None else "Matemática"
        created_ids: list[int] = []
        questions_out: list[GeneratedQuestion] = []

        for _ in range(count):
            question = await self._generate_one(
                materia=materia,
                conteudo=content.name,
                eixo=eixo,
                difficulty=difficulty,
            )
            exercise = Exercise(
                content_id=content_id,
                statement=question.statement,
                difficulty=_DIFFICULTY_MAP.get(question.difficulty, DifficultyEnum.EASY),
            )
            session.add(exercise)
            await session.flush()
            for option in question.options:
                session.add(
                    Option(
                        exercise_id=exercise.id,
                        text=option.text,
                        correct=option.correct,
                    )
                )
            created_ids.append(exercise.id)
            questions_out.append(
                GeneratedQuestion(
                    statement=question.statement,
                    difficulty=question.difficulty,
                    options=[
                        GeneratedOption(text=option.text, correct=option.correct)
                        for option in question.options
                    ],
                )
            )

        await session.commit()
        return {
            "content_id": content_id,
            "created_exercise_ids": created_ids,
            "questions": [question.model_dump() for question in questions_out],
        }

    async def _generate_one(
        self,
        materia: str,
        conteudo: str,
        eixo: list[str],
        difficulty: int,
    ) -> _LlmQuestion:
        """Generate one question via LLM or deterministic fallback."""
        if not settings.GOOGLE_API_KEY:
            return self._fallback_question(conteudo=conteudo, eixo=eixo, difficulty=difficulty)

        try:
            llm = ChatGoogleGenerativeAI(
                model=settings.GEMINI_MODEL,
                api_key=settings.GOOGLE_API_KEY,
                temperature=settings.LLM_GENERATION_TEMPERATURE,
            ).with_structured_output(_LlmQuestion)
            chain = _prompt | llm
            result = await chain.ainvoke(
                {
                    "eixo": eixo,
                    "conteudo": conteudo,
                    "materia": materia,
                    "dificuldade": difficulty,
                }
            )
            if sum(1 for option in result.options if option.correct) != 1:
                raise ValueError("LLM returned a question without exactly one correct option")
            return result  # type: ignore[return-value]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Question generation failed; using fallback: %s", exc)
            return self._fallback_question(conteudo=conteudo, eixo=eixo, difficulty=difficulty)

    def _fallback_question(
        self,
        conteudo: str,
        eixo: list[str],
        difficulty: int,
    ) -> _LlmQuestion:
        """Return a deterministic offline question for local/dev/test environments."""
        eixo_principal = eixo[0] if eixo else conteudo
        return _LlmQuestion(
            statement=f"Sobre {conteudo}, qual alternativa representa {eixo_principal}?",
            difficulty=difficulty,
            options=[
                _LlmOption(text=f"Ideia principal de {eixo_principal}.", correct=True),
                _LlmOption(text="Alternativa incorreta A.", correct=False),
                _LlmOption(text="Alternativa incorreta B.", correct=False),
                _LlmOption(text="Alternativa incorreta C.", correct=False),
            ],
        )
