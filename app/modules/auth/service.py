import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import DomainError
from app.db.models.identity import RefreshSession, User
from app.integrations import kakao
from app.modules.auth.schemas import LoginResult, TokenPair

ACCESS_LIFETIME = timedelta(minutes=15)
SESSION_LIFETIME = timedelta(days=30)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def unauthorized():
    return DomainError(401, "AUTH_REQUIRED", "로그인이 필요합니다.")


def rotate(row, now):
    access = "sa_" + secrets.token_urlsafe(32)
    refresh = "sr_" + secrets.token_urlsafe(32)
    row.access_hash, row.refresh_hash = digest(access), digest(refresh)
    row.access_expires_at = min(now + ACCESS_LIFETIME, row.expires_at)
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=int((row.access_expires_at - now).total_seconds()),
    )


def login(session, token):
    kakao_id = kakao.verify_access_token(token)
    with session.begin():
        user_id = session.scalar(
            insert(User)
            .values(kakao_user_id=kakao_id)
            .on_conflict_do_nothing(index_elements=[User.kakao_user_id])
            .returning(User.id)
        )
        if user_id is None:
            user_id = session.scalar(
                select(User.id).where(User.kakao_user_id == kakao_id).with_for_update()
            )
            if user_id is None:
                raise unauthorized()
        elif kakao.verify_access_token(token) != kakao_id:
            # A concurrent withdrawal may have unlinked this token while INSERT waited.
            raise unauthorized()
        now = datetime.now(UTC)
        session.execute(
            delete(RefreshSession).where(
                RefreshSession.user_id == user_id, RefreshSession.expires_at <= now
            )
        )
        row = RefreshSession(user_id=user_id, expires_at=now + SESSION_LIFETIME)
        session.add(row)
        return LoginResult(**rotate(row, now).model_dump(), user_id=user_id)


def refresh(session, token):
    with session.begin():
        row = session.scalar(
            select(RefreshSession)
            .where(RefreshSession.refresh_hash == digest(token))
            .with_for_update()
        )
        now = datetime.now(UTC)
        if row is None or row.expires_at <= now:
            raise unauthorized()
        return rotate(row, now)


def logout(session, account, token):
    with session.begin():
        result = session.execute(
            delete(RefreshSession).where(
                RefreshSession.id == account.session_id,
                RefreshSession.user_id == account.user_id,
                RefreshSession.refresh_hash == digest(token),
            )
        )
        if result.rowcount != 1:
            raise unauthorized()
