from fastapi import APIRouter, Response
from pydantic import Field, SecretStr, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.api.dependencies import Database
from app.core.errors import API_ERRORS
from app.core.idempotency import lock_key
from app.core.schemas import Input
from app.db.models.identity import RefreshSession
from app.db.models.push import PushDevice
from app.modules.auth.dependencies import Member
from app.modules.auth.service import unauthorized

router = APIRouter(tags=["push"], responses=API_ERRORS)


class PushToken(Input):
    token: SecretStr = Field(min_length=1, max_length=2048)

    @field_validator("token")
    @classmethod
    def validate_token(cls, value):
        token = value.get_secret_value()
        if not token.isascii() or not token.isprintable() or " " in token:
            raise ValueError("FCM 토큰 형식을 확인해 주세요.")
        return value


def lock_session(session, account):
    current = session.scalar(
        select(RefreshSession.id)
        .where(
            RefreshSession.id == account.session_id,
            RefreshSession.user_id == account.user_id,
            RefreshSession.expires_at > func.now(),
        )
        .with_for_update()
    )
    if current is None:
        raise unauthorized()
    return current


@router.put("/me/push-token", status_code=204)
def register_token(data: PushToken, account: Member, session: Database):
    token = data.token.get_secret_value()
    with session.begin():
        # Registrations can move a token between sessions or swap two tokens.
        lock_key(session, "push-device-binding")
        current = lock_session(session, account)
        session.execute(
            delete(PushDevice).where(
                PushDevice.token == token,
                PushDevice.session_id != current,
            )
        )
        session.execute(
            insert(PushDevice)
            .values(session_id=current, token=token)
            .on_conflict_do_update(index_elements=[PushDevice.session_id], set_={"token": token})
        )
    return Response(status_code=204)


@router.delete("/me/push-token", status_code=204)
def disable_push(account: Member, session: Database):
    with session.begin():
        current = lock_session(session, account)
        session.execute(delete(PushDevice).where(PushDevice.session_id == current))
    return Response(status_code=204)
