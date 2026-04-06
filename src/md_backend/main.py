"""Main file."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from md_backend.routes.router import router
from md_backend.utils.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables on startup."""
    await init_db()
    yield


app = FastAPI(lifespan=lifespan)

app.include_router(router)


@app.get("/")
async def root():
    """Check if service is alive."""
    return {"detail": "Alive!"}
