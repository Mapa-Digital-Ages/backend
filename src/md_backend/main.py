"""Main file."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from md_backend.routes.router import router
from md_backend.utils.database import engine, init_db
from md_backend.utils.limiter import limiter
from md_backend.utils.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables on startup, dispose engine on shutdown."""
    await init_db()
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(router, prefix="/api")


@app.get("/api")
async def root():
    """Check if service is alive."""
    return {"detail": "Alive!"}
