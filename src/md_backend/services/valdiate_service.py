"""ValidateService file."""

from md_backend.utils.settings import settings


class ValidateService:
    """Validate Service."""

    async def process_text(self, text: str, sender: str) -> str:
        """Module to process text."""
        final_message = f"{sender} sent the message '{text}' with variable {settings.TEST_VARIABLE}"
        return final_message
