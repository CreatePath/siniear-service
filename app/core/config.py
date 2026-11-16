from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    db_host: str = "127.0.0.1"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "siniear"
    db_user: str = "siniear"
    db_password: SecretStr = Field(min_length=1)
    app_env: Literal["development", "test", "production"] = "production"
    dev_auth_enabled: bool = False

    @model_validator(mode="after")
    def guard_dev_auth(self):
        if self.dev_auth_enabled and self.app_env == "production":
            raise ValueError("Development authentication is forbidden in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
