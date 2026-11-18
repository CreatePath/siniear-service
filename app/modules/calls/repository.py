import re

from sqlalchemy import select

from app.core.errors import DomainError
from app.db.models.call import Call, CallEpisode, CallSchedule
from app.db.models.identity import IdentityVerification, Senior

TERMINAL = {"completed", "busy", "no_answer", "failed", "canceled"}
ACTIVE = {"queued", "initiated", "ringing", "in_progress"}


def senior_for_call(session, call_id, *, lock=False):
    query = (
        select(Senior)
        .join(CallSchedule, CallSchedule.senior_id == Senior.id)
        .join(CallEpisode, CallEpisode.schedule_id == CallSchedule.id)
        .join(Call, Call.episode_id == CallEpisode.id)
        .where(Call.id == call_id)
    )
    if lock:
        query = query.with_for_update(of=Senior, key_share=True)
    senior = session.scalar(query.execution_options(populate_existing=True))
    if senior is None:
        raise DomainError(404, "CALL_NOT_FOUND", "통화를 찾을 수 없습니다.")
    return senior


def eligible(session, senior):
    return bool(
        senior.call_agree
        and re.fullmatch(r"\+[1-9][0-9]{7,14}", senior.phone_number)
        and session.scalar(
            select(IdentityVerification.id)
            .where(
                IdentityVerification.user_id == senior.user_id,
                IdentityVerification.status == "verified",
                IdentityVerification.verified_at.is_not(None),
            )
            .limit(1)
        )
    )


def require_eligible(session, senior):
    if not eligible(session, senior):
        raise DomainError(403, "CALL_NOT_ALLOWED", "전화 동의와 회원 정보를 확인해 주세요.")


def call_query(senior_id):
    return (
        select(Call)
        .join(CallEpisode, Call.episode_id == CallEpisode.id)
        .join(CallSchedule, CallEpisode.schedule_id == CallSchedule.id)
        .where(CallSchedule.senior_id == senior_id)
    )
