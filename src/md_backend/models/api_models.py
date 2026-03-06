"""Store API models."""

from pydantic import BaseModel


class ValidateRequest(BaseModel):
    """Validate request model."""

    text: str
    sender: str
