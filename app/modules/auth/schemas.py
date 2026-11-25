from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr

from app.core.schemas import Input

Credential = Annotated[SecretStr, Field(min_length=1, max_length=4096)]


class KakaoLogin(Input):
    access_token: Credential


class RefreshInput(Input):
    refresh_token: Credential


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class LoginResult(TokenPair):
    user_id: UUID
    verification_status: Literal["not_required"] = "not_required"


class MyAccount(BaseModel):
    user_id: UUID
    senior_id: UUID | None
    roles: list[Literal["senior"]]
    verification_status: Literal["not_required"] = "not_required"
