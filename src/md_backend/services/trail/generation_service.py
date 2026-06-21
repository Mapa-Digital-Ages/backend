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

_SYSTEM_PROMPT = """Você é um gerador de questões objetivas de múltipla escolha em português
(PT-BR) para alunos do 5º ao 9º ano. Gere a quantidade pedida de questões que testem
DIRETAMENTE o eixo informado, no contexto do conteúdo dado.

Regras obrigatórias:
- Gere EXATAMENTE a quantidade pedida de questões, todas DISTINTAS entre si.
- Varie os números, os contextos e o formato: misture cálculo direto e problemas
  contextualizados (situações do dia a dia). Nunca repita o mesmo enunciado nem os mesmos
  valores entre as questões.
- Cada questão tem EXATAMENTE 4 alternativas e EXATAMENTE 1 correta.
- Os distratores (alternativas erradas) devem ser plausíveis, refletindo erros comuns do
  aluno (ex.: esquecer de inverter a operação). Nunca use textos genéricos como
  "Alternativa incorreta" ou "Ideia principal de".
- Não inclua letras/marcadores como "a)" no texto das alternativas.
- Respeite a dificuldade pedida: 1=fácil, 2=médio, 3=difícil."""
_HUMAN_PROMPT = (
    "quantidade: {quantidade}\neixo: {eixo}\nconteudo: {conteudo}\n"
    "materia: {materia}\ndificuldade: {dificuldade}"
)
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


class _LlmQuiz(BaseModel):
    """A batch of distinct questions returned by the LLM in a single call."""

    questions: list[_LlmQuestion] = Field(
        ..., description="Lista de questões distintas entre si.", min_length=1
    )


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

        # The step defines the difficulty; store that level for every question
        # instead of the LLM's self-assessment (which can drift from the request).
        stored_difficulty = _DIFFICULTY_MAP.get(difficulty, DifficultyEnum.EASY)

        questions = await self._generate_batch(
            materia=materia,
            conteudo=content.name,
            eixo=eixo,
            count=count,
            difficulty=difficulty,
        )

        for question in questions:
            exercise = Exercise(
                content_id=content_id,
                statement=question.statement,
                difficulty=stored_difficulty,
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
                    difficulty=difficulty,
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

    def _build_llm(self) -> ChatGoogleGenerativeAI:
        """Construct the Gemini client with a low retry cap for fast fallback."""
        return ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            api_key=settings.GOOGLE_API_KEY,
            temperature=settings.LLM_GENERATION_TEMPERATURE,
            max_retries=settings.LLM_GENERATION_MAX_RETRIES,
        )

    async def _generate_batch(
        self,
        materia: str,
        conteudo: str,
        eixo: list[str],
        count: int,
        difficulty: int,
    ) -> list[_LlmQuestion]:
        """Generate `count` distinct questions in one LLM call (or deterministic fallback).

        A single batched call lets the model see all questions at once (so they vary),
        and uses one request instead of `count` — avoiding free-tier rate limits.
        """
        if not settings.GOOGLE_API_KEY:
            return self._fallback_batch(
                conteudo=conteudo, eixo=eixo, count=count, difficulty=difficulty
            )

        try:
            llm = self._build_llm().with_structured_output(_LlmQuiz)
            chain = _prompt | llm
            result = await chain.ainvoke(
                {
                    "quantidade": count,
                    "eixo": eixo,
                    "conteudo": conteudo,
                    "materia": materia,
                    "dificuldade": difficulty,
                }
            )
            questions = list(result.questions)  # type: ignore[union-attr]
            if len(questions) != count:
                raise ValueError(f"LLM returned {len(questions)} questions, expected {count}")
            for question in questions:
                if sum(1 for option in question.options if option.correct) != 1:
                    raise ValueError("LLM returned a question without exactly one correct option")
            return questions
        except Exception as exc:  # noqa: BLE001
            logger.warning("Question generation failed; using fallback: %s", exc)
            return self._fallback_batch(
                conteudo=conteudo, eixo=eixo, count=count, difficulty=difficulty
            )

    def _fallback_batch(
        self,
        conteudo: str,
        eixo: list[str],
        count: int,
        difficulty: int,
    ) -> list[_LlmQuestion]:
        """Return `count` distinct deterministic questions for offline/dev/test use."""
        eixo_principal = eixo[0] if eixo else conteudo
        return [
            _LlmQuestion(
                statement=(
                    f"Questão {index} sobre {conteudo} (eixo: {eixo_principal}). "
                    "Selecione a alternativa correta."
                ),
                difficulty=difficulty,
                options=[
                    _LlmOption(text=f"Resposta correta da questão {index}.", correct=True),
                    _LlmOption(text=f"Distrator {index}-A.", correct=False),
                    _LlmOption(text=f"Distrator {index}-B.", correct=False),
                    _LlmOption(text=f"Distrator {index}-C.", correct=False),
                ],
            )
            for index in range(1, count + 1)
        ]
