from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import DomainError
from app.db.models.identity import RefreshSession, Senior, User
from app.db.session import get_session
from app.modules.auth.service import digest, unauthorized


@dataclass(frozen=True)
class Account:
    user_id: UUID
    senior_id: UUID | None
    session_id: UUID | None


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    senior_id: UUID


bearer = HTTPBearer(auto_error=False)


def get_account(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> Account:
    if credentials is None:
        raise unauthorized()
    token = credentials.credentials
    query = (
        select(User.id, Senior.id)
        .outerjoin(Senior, Senior.user_id == User.id)
        .where(User.withdrawn_at.is_(None))
    )
    if token.startswith("dev:"):
        settings = get_settings()
        if not settings.dev_auth_enabled or settings.app_env not in {"development", "test"}:
            raise unauthorized()
        try:
            dev_id = UUID(token[4:])
        except ValueError:
            raise unauthorized() from None
        query = query.where(User.id == dev_id, User.kakao_user_id.is_(None))
    elif token.startswith("sa_") and len(token) == 46:
        query = (
            query.add_columns(RefreshSession.id)
            .join(RefreshSession, RefreshSession.user_id == User.id)
            .where(
                RefreshSession.access_hash == digest(token),
                RefreshSession.access_expires_at > datetime.now(UTC),
            )
        )
    else:
        raise unauthorized()
    with session.begin():
        row = session.execute(query).one_or_none()
        if row is None:
            raise unauthorized()
        return Account(row[0], row[1], row[2] if len(row) == 3 else None)


Member = Annotated[Account, Depends(get_account)]


def get_principal(account: Member, session: Annotated[Session, Depends(get_session)]) -> Principal:
    if account.senior_id is None:
        raise DomainError(403, "PROFILE_REQUIRED", "먼저 회원 프로필을 등록해 주세요.")

    # The business transaction must finish before withdrawal can anonymize this member.
    @event.listens_for(session, "after_begin", once=True)
    def lock_active_member(_session, _transaction, connection):
        active = connection.scalar(
            select(User.id)
            .where(User.id == account.user_id, User.withdrawn_at.is_(None))
            .with_for_update(read=True)
        )
        if active is None:
            raise unauthorized()

    return Principal(account.user_id, account.senior_id)
