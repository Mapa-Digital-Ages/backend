"""Routes for the LLM question trail feature."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from md_backend.models.api_models import (
    IniciarTrilhaRequest,
    PerguntaResponse,
    ResponderPerguntaRequest,
)
from md_backend.services import trilha_service
from md_backend.utils.access_control import is_active_student
from md_backend.utils.database import get_db_session
from md_backend.utils.handle_errors import handle_errors
from md_backend.utils.security import get_current_approved_user
from md_backend.utils.singletons import get_redis

trilha_router = APIRouter(prefix="/trilha", tags=["trilha"])


@trilha_router.post("/iniciar", response_model=PerguntaResponse, status_code=201)
@handle_errors
async def iniciar_trilha(
    req: IniciarTrilhaRequest,
    current_user: dict = Depends(get_current_approved_user),
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
) -> PerguntaResponse:
    """Start a new question trail for the authenticated student."""
    student_id = uuid.UUID(current_user["user_id"])

    if not await is_active_student(session=db, user_id=student_id):
        raise HTTPException(status_code=403, detail="Acesso restrito a alunos ativos")

    return await trilha_service.iniciar_trilha(student_id=student_id, req=req, redis=redis)


@trilha_router.post("/{trilha_id}/responder")
@handle_errors
async def responder_pergunta(
    trilha_id: str,
    req: ResponderPerguntaRequest,
    current_user: dict = Depends(get_current_approved_user),
    db: AsyncSession = Depends(get_db_session),
    redis=Depends(get_redis),
) -> StreamingResponse:
    """Submit an answer. Streams two SSE events: 'resultado' then 'proxima_pergunta'."""
    raw = await redis.get(f"trilha:{trilha_id}")
    if raw is None:
        raise HTTPException(status_code=404, detail="Trilha não encontrada ou expirada")

    estado = json.loads(raw)

    if estado["student_id"] != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Trilha pertence a outro aluno")

    stream = await trilha_service.responder_pergunta_stream(
        trilha_id=trilha_id,
        estado=estado,
        req=req,
        redis=redis,
        db=db,
    )

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
