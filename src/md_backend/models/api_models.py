"""Store API models."""

import datetime

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

class StudentResponse(BaseModel):
    """Response model for student creation."""

    id: int
    user_id: int
    first_name: str
    last_name: str
    email: str
    birth_date: str
    student_class: str
    created_at: str

class StudentRequest(BaseModel):
    """Request model for creating a new student."""

    first_name: str
    last_name: str
    email: EmailStr
    password: str = Field(min_length=8)
    birth_date: datetime.date
    student_class: str

class StudentListResponse(BaseModel):
    """Response model for student listing."""

    id: int
    user_id: int
    first_name: str
    last_name: str
    email: str
    phone_number: str
    birth_date: str
    student_class: str
    school_id: str
    is_active: bool
    created_at: str | None

class CreateSchoolRequest(BaseModel):
    """Request body for POST /schools."""

    first_name: str = Field(min_length=1, description="Primeiro nome")
    last_name: str = Field(min_length=1, description="Sobrenome")
    email: EmailStr = Field(description="E-mail")
    password: str = Field(min_length=8, description="Senha de acesso com mínimo de 8 caracteres")
    is_private: bool = Field(description="Indica se a escola é pública ou privada")
    cnpj: str = Field(min_length=14, max_length=18, description="CNPJ da escola")
