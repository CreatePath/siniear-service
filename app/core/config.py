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
    interview_provider: Literal["fake", "gemini"] = "fake"
    gemini_api_key: SecretStr | None = None
    gemini_interview_model: str = Field(default="", pattern=r"^[a-zA-Z0-9._-]*$")

    kakao_app_id: int = Field(default=0, ge=0)
    kakao_admin_key: SecretStr = SecretStr("")

    internal_inbound_token: SecretStr = SecretStr("")
    internal_outbound_token: SecretStr = SecretStr("")
    internal_peer: str = "T"
    internal_scopes: str = "calls:events meetings:read meetings:write interests:write alerts:read"
    peer_base_url: str = "http://call:8000"

    @model_validator(mode="after")
    def guard_dev_auth(self):
        if self.dev_auth_enabled and self.app_env == "production":
            raise ValueError("Development authentication is forbidden in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
