"""Main file."""

from fastapi import FastAPI

from md_backend.routes.router import router

app = FastAPI()

app.include_router(router)


@app.get("/")
async def root():
    """Check if service is alive."""
    return {"detail": "Alive!"}
