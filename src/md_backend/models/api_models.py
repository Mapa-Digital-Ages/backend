"""Store API models."""

import datetime
import enum

from pydantic import BaseModel, EmailStr, Field

from md_backend.models.db_models import ClassEnum


class UserStatusInput(str, enum.Enum):
    """User approval status values used in API layer."""

    AGUARDANDO = "aguardando"
    APROVADO = "aprovado"
    NEGADO = "negado"


class RoleInput(str, enum.Enum):
    """User role values used in API layer."""

    ADMIN = "admin"
    ALUNO = "aluno"
    RESPONSAVEL = "responsavel"


class ValidateRequest(BaseModel):
    """Validate request model."""

    text: str
    sender: str


class RegisterRequest(BaseModel):
    """Register request model."""

    name: str = Field()
    email: EmailStr
    password: str = Field(min_length=8)


class AlunoRegisterRequest(BaseModel):
    """Register request model for aluno (requires school-specific fields)."""

    name: str = Field()
    email: EmailStr
    password: str = Field(min_length=8)
    birth_date: datetime.date
    student_class: ClassEnum


class LoginRequest(BaseModel):
    """Login request model."""

    email: EmailStr
    password: str


class SetupRequest(BaseModel):
    """Setup request model for creating the first superadmin."""

    email: EmailStr
    password: str = Field(min_length=8)


class UserResponse(BaseModel):
    """User data for admin listing."""

    id: str
    email: str
    name: str
    status: str
    is_superadmin: bool
    created_at: str


class UpdateStatusRequest(BaseModel):
    """Request to update user approval status."""

    status: str = Field(pattern=r"^(aprovado|negado)$")
