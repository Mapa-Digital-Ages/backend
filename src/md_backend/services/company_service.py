"""Company Services - handles atomic creation of company accounts."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Importações essenciais que você vai precisar usar:
from md_backend.models.db_models import Company, RoleEnum, User, UserStatus
from md_backend.utils.security import hash_password


class CompanyService:
    """Service for company-related operations."""

    async def create_company(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        cnpj: str,
        session: AsyncSession,
    ) -> dict | None:
        """Create a company atomically (user_profile + company_profile)."""
        # TODO: Implemente a lógica aqui! 
        # Dica: Abra o school_service.py na outra aba e vá seguindo os passos.
        pass
