"""Settings module for the service."""

from typing import Literal

from dotenv import find_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings class for configuring the service."""

    model_config = SettingsConfigDict(
        env_file=find_dotenv(), env_file_encoding="utf-8", extra="ignore"
    )

    TEST_VARIABLE: str = ""

    # Database
    DATABASE_URL: str = ""

    # Security — both fields are required and must be at least 32 characters.
    # An empty or short value means the service was deployed without secrets configured.
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 30
    PASSWORD_PEPPER: str = Field(min_length=32)

    # CORS — comma-separated list of allowed origins, e.g. "http://localhost:5173,https://app.example.com"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Storage
    STORAGE_BACKEND: Literal["postgres", "s3"] = "postgres"
    AWS_S3_BUCKET: str | None = None
    AWS_S3_REGION: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_S3_ENDPOINT_URL: str | None = (
        None  # overrides default AWS endpoint; use for MinIO/localstack
    )


settings = Settings()  # type: ignore
