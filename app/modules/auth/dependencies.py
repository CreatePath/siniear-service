from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import DomainError
from app.db.models import IdentityVerification, Senior
from app.db.session import get_session


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    senior_id: UUID


bearer = HTTPBearer(auto_error=False)


def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> Principal:
    settings = get_settings()
    if not settings.dev_auth_enabled or settings.app_env not in {"development", "test"}:
        raise DomainError(401, "AUTH_REQUIRED", "인증이 필요합니다.")
    try:
        if credentials is None or not credentials.credentials.startswith("dev:"):
            raise ValueError
        user_id = UUID(credentials.credentials[4:])
    except ValueError:
        raise DomainError(401, "AUTH_REQUIRED", "개발용 인증 계정을 확인해 주세요.") from None
    # Separate read transaction: business services own their transaction boundaries.
    with session.begin():
        senior = session.scalar(select(Senior).where(Senior.user_id == user_id))
        if senior is None:
            raise DomainError(401, "AUTH_REQUIRED", "계정을 확인해 주세요.")
        verified = session.scalar(
            select(IdentityVerification.id)
            .where(
                IdentityVerification.user_id == user_id,
                IdentityVerification.status == "verified",
                IdentityVerification.verified_at.is_not(None),
            )
            .limit(1)
        )
        if verified is None:
            raise DomainError(403, "IDENTITY_REQUIRED", "실명 인증이 필요합니다.")
        return Principal(user_id, senior.id)
