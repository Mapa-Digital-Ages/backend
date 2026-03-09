"""Settings module for the service."""

from dotenv import find_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings class for configuring the service."""

    model_config = SettingsConfigDict(
        env_file=find_dotenv(), env_file_encoding="utf-8", extra="ignore"
    )

    TEST_VARIABLE: str = ""
    # other variables set here:


settings = Settings()  # type: ignore
