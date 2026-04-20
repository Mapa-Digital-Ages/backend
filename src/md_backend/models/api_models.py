"""Store API models."""

from pydantic import BaseModel, EmailStr, Field


class ValidateRequest(BaseModel):
    """Validate request model."""

    text: str
    sender: str


class RegisterRequest(BaseModel):
    """Register request model."""

    name: str = Field()
    email: EmailStr
    password: str = Field(min_length=8)


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

    id: int
    email: str
    name: str
    status: str
    is_superadmin: bool
    created_at: str


class UpdateStatusRequest(BaseModel):
    """Request to update user approval status."""

    status: str = Field(pattern=r"^(aprovado|negado)$")


class CreateSchoolRequest(BaseModel):
    """Request body for POST /schools."""

    first_name: str = Field(min_length=1, description="Primeiro nome")
    last_name: str = Field(min_length=1, description="Sobrenome")
    email: EmailStr = Field(description="E-mail")
    password: str = Field(min_length=8, description="Senha de acesso com mínimo de 8 caracteres")
    is_private: bool = Field(description="Indica se a escola é pública ou privada")
    cnpj: str = Field(min_length=14, max_length=18, description="CNPJ da escola")

class SchoolResponse(BaseModel):
    """Response model for a single school - password is never included."""

    user_id: int
    email: str
    name: str
    cnpj: str
    is_private: bool
    status: str
    created_at: str
    is_active: bool
    quantidade_alunos: int

class SchoolListResponse(BaseModel):
    """Paginated list of schools."""

    items: list[SchoolResponse]
    total: int
    page: int
    size: int