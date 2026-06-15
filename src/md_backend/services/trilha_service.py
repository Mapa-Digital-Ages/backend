"""Business logic and LLM question generation for the trilha feature."""

import datetime
import json
import uuid
from collections.abc import AsyncGenerator
from typing import Literal

import redis.asyncio as aioredis
from fastapi import HTTPException
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    IniciarTrilhaRequest,
    PerguntaResponse,
    ResponderPerguntaRequest,
)
from md_backend.models.db_models import TrilhaResultado, TrilhaStatusEnum
from md_backend.utils.logger import get_logger
from md_backend.utils.settings import settings
from md_backend.utils.singletons import get_llm

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Você é um gerador de questões objetivas em português.

Público-alvo: alunos do 5º ao 9º ano do Ensino Fundamental (≈10 a 14 anos).
Use linguagem clara, vocabulário acessível e contextos próximos da realidade dessa faixa
etária. Evite jargão técnico desnecessário e enunciados longos.

Foco da pergunta:
- A pergunta deve testar DIRETAMENTE o `eixo` informado, não apenas tangenciá-lo.
- O enunciado e as alternativas devem exigir do aluno a habilidade/competência específica
daquele eixo aplicada ao `conteudo` e `materia`.
- Distratores plausíveis, coerentes com erros típicos de alunos dessa faixa no eixo em questão.

Regras obrigatórias:
- Gere UMA pergunta objetiva sobre o conteúdo informado.
- Forneça exatamente 4 alternativas no campo `respostas` como objeto JSON com
chaves "a", "b", "c", "d".
- Exatamente UMA alternativa é correta. Indique-a em `resposta_certa` usando a
letra ("a", "b", "c" ou "d").
- Respeite a dificuldade pedida: 1 = fácil, 2 = médio, 3 = difícil — calibrada para 5º-9º ano.
- Ecoe nos campos `eixo`, `conteudo`, `materia` e `dificuldade` exatamente os valores recebidos.
- Não inclua a letra ("a)", "b)" etc.) dentro do texto de cada alternativa; apenas o texto.
"""

_HUMAN_PROMPT = """Gere uma pergunta com:
- eixo: {eixo}
- conteudo: {conteudo}
- materia: {materia}
- dificuldade: {dificuldade}
"""

_prompt = ChatPromptTemplate.from_messages([("system", _SYSTEM_PROMPT), ("human", _HUMAN_PROMPT)])

# ---------------------------------------------------------------------------
# LLM models (internal — never exposed in the API)
# ---------------------------------------------------------------------------


class RespostasMap(BaseModel):
    """Map of answer letter to answer text."""

    a: str = Field(..., description="Texto da alternativa A.")
    b: str = Field(..., description="Texto da alternativa B.")
    c: str = Field(..., description="Texto da alternativa C.")
    d: str = Field(..., description="Texto da alternativa D.")


class Pergunta(BaseModel):
    """Structured output model for LLM question generation."""

    pergunta: str = Field(..., description="Enunciado da pergunta objetiva.")
    respostas: RespostasMap = Field(
        ...,
        description='Objeto com chaves "a", "b", "c", "d" contendo o texto de cada alternativa.',
    )
    resposta_certa: Literal["a", "b", "c", "d"] = Field(
        ..., description="Letra da alternativa correta."
    )
    dificuldade: int = Field(..., ge=1, le=3, description="1=fácil, 2=médio, 3=difícil.")
    eixo: list[str]
    conteudo: str
    materia: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict) -> str:
    """Format a server-sent event string."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _gerar_pergunta(
    materia: str,
    conteudo: str,
    eixo: list[str],
    dificuldade: int,
) -> Pergunta:
    """Generate a single question via LLM with structured output."""
    logger.debug(
        "Gerando pergunta: materia=%s conteudo=%s eixo=%s dificuldade=%d",
        materia,
        conteudo,
        eixo,
        dificuldade,
    )
    llm = get_llm().with_structured_output(Pergunta)
    chain = _prompt | llm
    result = await chain.ainvoke(
        {"eixo": eixo, "conteudo": conteudo, "materia": materia, "dificuldade": dificuldade}
    )
    logger.debug("Pergunta gerada: resposta_certa=%s", result.resposta_certa)  # type: ignore[union-attr]
    return result  # type: ignore[return-value]


def _pergunta_estado(pergunta_id: str, pergunta: Pergunta) -> dict:
    """Build the pergunta_atual dict stored in Redis."""
    return {
        "pergunta_id": pergunta_id,
        "pergunta": pergunta.pergunta,
        "respostas": pergunta.respostas.model_dump(),
        "resposta_certa": pergunta.resposta_certa,
        "dificuldade": pergunta.dificuldade,
    }


def _pergunta_response(
    trilha_id: str, pergunta_id: str, pergunta: Pergunta, tentativas_restantes: int
) -> dict:
    """Build the PerguntaResponse dict for SSE or direct return."""
    return PerguntaResponse(
        trilha_id=trilha_id,
        pergunta_id=pergunta_id,
        pergunta=pergunta.pergunta,
        respostas=pergunta.respostas.model_dump(),
        dificuldade=pergunta.dificuldade,
        tentativas_restantes=tentativas_restantes,
    ).model_dump()


# ---------------------------------------------------------------------------
# Trail service
# ---------------------------------------------------------------------------


async def iniciar_trilha(
    student_id: uuid.UUID,
    req: IniciarTrilhaRequest,
    redis: aioredis.Redis,
) -> PerguntaResponse:
    """Start a new trail: generate the first question and store state in Redis."""
    trilha_id = f"t_{uuid.uuid4()}"
    pergunta_id = f"p_{uuid.uuid4()}"

    logger.info(
        "Iniciando trilha: student_id=%s materia=%s conteudo=%s trilha_id=%s",
        student_id,
        req.materia,
        req.conteudo,
        trilha_id,
    )

    pergunta = await _gerar_pergunta(
        materia=req.materia, conteudo=req.conteudo, eixo=req.eixo, dificuldade=1
    )

    estado = {
        "student_id": str(student_id),
        "materia": req.materia,
        "conteudo": req.conteudo,
        "eixo": req.eixo,
        "dificuldade_atual": 1,
        "tentativas_usadas": 0,
        "status": "in_progress",
        "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "pergunta_atual": _pergunta_estado(pergunta_id, pergunta),
    }

    await redis.set(f"trilha:{trilha_id}", json.dumps(estado), ex=settings.TRILHA_TTL_SECONDS)
    logger.info("Trilha %s salva no Redis (TTL=%ds)", trilha_id, settings.TRILHA_TTL_SECONDS)

    return PerguntaResponse(
        trilha_id=trilha_id,
        pergunta_id=pergunta_id,
        pergunta=pergunta.pergunta,
        respostas=pergunta.respostas.model_dump(),
        dificuldade=1,
        tentativas_restantes=5,
    )


async def responder_pergunta_stream(
    trilha_id: str,
    estado: dict,
    req: ResponderPerguntaRequest,
    redis: aioredis.Redis,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """Validate answer and stream: resultado event first, proxima_pergunta after LLM."""
    if estado["pergunta_atual"]["pergunta_id"] != req.pergunta_id:
        raise HTTPException(status_code=400, detail="pergunta_id inválido — não é a pergunta ativa")

    estado["tentativas_usadas"] += 1
    tentativas_usadas: int = estado["tentativas_usadas"]
    dificuldade_atual: int = estado["dificuldade_atual"]
    correto: bool = req.resposta == estado["pergunta_atual"]["resposta_certa"]

    # Determine final status before any async work
    if correto and dificuldade_atual == 3:
        proximo_status = "passed"
    elif not correto and tentativas_usadas == 5:
        proximo_status = "failed"
    else:
        proximo_status = "in_progress"

    logger.info(
        "Resposta trilha=%s pergunta=%s correto=%s tentativas=%d status=%s",
        trilha_id,
        req.pergunta_id,
        correto,
        tentativas_usadas,
        proximo_status,
    )

    return _stream_resposta(
        trilha_id=trilha_id,
        estado=estado,
        correto=correto,
        proximo_status=proximo_status,
        dificuldade_atual=dificuldade_atual,
        tentativas_usadas=tentativas_usadas,
        redis=redis,
        db=db,
    )


async def _stream_resposta(
    trilha_id: str,
    estado: dict,
    correto: bool,
    proximo_status: str,
    dificuldade_atual: int,
    tentativas_usadas: int,
    redis: aioredis.Redis,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """Async generator: yield resultado immediately, then proxima_pergunta after LLM."""
    # Event 1 — immediate, no LLM needed
    yield _sse(
        "resultado",
        {
            "correto": correto,
            "status": proximo_status,
            "tentativas_restantes": 5 - tentativas_usadas,
        },
    )

    if proximo_status == "in_progress":
        nova_dificuldade = dificuldade_atual + 1 if correto else dificuldade_atual
        nova_pergunta = await _gerar_pergunta(
            materia=estado["materia"],
            conteudo=estado["conteudo"],
            eixo=estado["eixo"],
            dificuldade=nova_dificuldade,
        )
        novo_pergunta_id = f"p_{uuid.uuid4()}"
        estado["dificuldade_atual"] = nova_dificuldade
        estado["pergunta_atual"] = _pergunta_estado(novo_pergunta_id, nova_pergunta)
        await redis.set(f"trilha:{trilha_id}", json.dumps(estado), keepttl=True)

        # Event 2 — after LLM finishes
        yield _sse(
            "proxima_pergunta",
            _pergunta_response(trilha_id, novo_pergunta_id, nova_pergunta, 5 - tentativas_usadas),
        )

    else:
        status_enum = TrilhaStatusEnum.PASSED if correto else TrilhaStatusEnum.FAILED
        logger.info("Trilha %s encerrada: status=%s", trilha_id, status_enum.value)
        await _salvar_resultado(db, trilha_id, estado, status_enum)
        await redis.delete(f"trilha:{trilha_id}")


async def _salvar_resultado(
    db: AsyncSession,
    trilha_id: str,
    estado: dict,
    status: TrilhaStatusEnum,
) -> None:
    """Persist the final trail result to the database."""
    logger.info(
        "Salvando resultado: trilha=%s student=%s status=%s dificuldade_final=%d tentativas=%d",
        trilha_id,
        estado["student_id"],
        status.value,
        estado["dificuldade_atual"],
        estado["tentativas_usadas"],
    )
    resultado = TrilhaResultado(
        trilha_id=trilha_id,
        student_id=uuid.UUID(estado["student_id"]),
        materia=estado["materia"],
        conteudo=estado["conteudo"],
        eixo=estado["eixo"],
        status=status,
        dificuldade_final=estado["dificuldade_atual"],
        tentativas_total=estado["tentativas_usadas"],
        started_at=datetime.datetime.fromisoformat(estado["started_at"]),
    )
    db.add(resultado)
    await db.commit()
