"""Lazy-initialized singletons: LLM client and Redis client."""

import redis.asyncio as aioredis
from langchain_google_genai import ChatGoogleGenerativeAI

from md_backend.utils.logger import get_logger
from md_backend.utils.settings import settings

logger = get_logger(__name__)

_llm: ChatGoogleGenerativeAI | None = None
_redis: aioredis.Redis | None = None


def get_llm() -> ChatGoogleGenerativeAI:
    """Return the singleton ChatGoogleGenerativeAI instance (sync, lazy init).

    Safe to call from module-level or sync context. The first call
    creates the instance; subsequent calls return the cached one.
    """
    global _llm  # noqa: PLW0603

    if _llm is None:
        _llm = ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            api_key=settings.GOOGLE_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
        )

    return _llm


def get_redis() -> aioredis.Redis:
    """Return the singleton Redis client (lazy init).

    Safe to call from sync or async context. Connection is established
    lazily on first command.
    """
    global _redis  # noqa: PLW0603

    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        logger.info("Redis client initialized")

    return _redis
