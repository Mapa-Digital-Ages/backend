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

class CreateCompanyRequest(BaseModel):
    """Request body for POST /companies."""
    
    first_name: str = Field(min_length=1, description="Primeiro nome")
    last_name: str = Field(min_length=1, description="Sobrenome")
    email: EmailStr = Field(description="E-mail corporativo")
    password: str = Field(min_length=8, description="Senha de acesso com mínimo de 8 caracteres")
    cnpj: str = Field(min_length=14, max_length=18, description="CNPJ da empresa")
    spots: int = Field(gt=0, description="Quantidade total de vagas oferecidas")

class CompanyResponse(BaseModel):
    """Response for company data."""

    user_id: int
    email: EmailStr
    name: str
    cnpj: str
    spots: int
    available_spots: int
    status: str
    created_at: str