"""ValidateService file."""

from md_backend.utils.settings import settings


class ValidateService:
    """Validate Service."""

    async def sum_numbers(self, num1: int, num2: int) -> int:
        return num1 + num2
