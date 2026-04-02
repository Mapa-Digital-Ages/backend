"""ValidateService file."""

from md_backend.utils.settings import settings


class ValidateService:
    """Validate Service."""

    async def process_text(self, num1: float, num2: float) -> float:
        return num1 * num2
