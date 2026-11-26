"""Send committed title awards to the device sessions registered at award time."""

import logging
import os
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models.identity import RefreshSession
from app.db.models.membership import Membership, MembershipTitle
from app.db.models.push import PushDevice, TitlePushDelivery
from app.db.session import get_engine
from app.integrations.fcm import FcmSender, PushRejected, RetryPush, UnregisteredToken

logger = logging.getLogger(__name__)


def deliver_one(session, sender):
    with session.begin():
        row = session.execute(
            select(
                TitlePushDelivery,
                PushDevice,
                MembershipTitle,
                Membership.left_at,
                RefreshSession.expires_at,
            )
            .join(PushDevice, PushDevice.session_id == TitlePushDelivery.session_id)
            .join(RefreshSession, RefreshSession.id == PushDevice.session_id)
            .join(MembershipTitle, MembershipTitle.id == TitlePushDelivery.title_id)
            .join(Membership, Membership.id == MembershipTitle.membership_id)
            .where(TitlePushDelivery.next_attempt_at <= func.now())
            .order_by(
                TitlePushDelivery.next_attempt_at,
                TitlePushDelivery.session_id,
                TitlePushDelivery.title_id,
            )
            .limit(1)
            .with_for_update(of=[PushDevice, TitlePushDelivery], key_share=True, skip_locked=True)
        ).one_or_none()
        if row is None:
            return False
        job, device, title, left_at, expires_at = row
        if left_at is not None or expires_at <= datetime.now(UTC):
            session.delete(job)
            return True
        try:
            sender.send(device.token, title)
        except UnregisteredToken:
            session.delete(device)  # Cascades all pending sends to this registration.
        except RetryPush as exc:
            job.attempts += 1
            if job.attempts < 10:
                delay = max(exc.delay, min(3600, 60 * 2 ** (job.attempts - 1)))
                job.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
                logger.warning("칭호 푸시 발송을 재시도합니다.")
            else:
                session.delete(job)
                logger.error("칭호 푸시 재시도 횟수를 소진했습니다.")
        except PushRejected:
            session.delete(job)
            logger.error("FCM이 칭호 알림 메시지를 거절했습니다.")
        else:
            session.delete(job)
        return True


def main():
    project = os.environ.get("FCM_PROJECT_ID")
    if not project:
        raise SystemExit("FCM_PROJECT_ID 설정이 필요합니다.")
    sender = FcmSender(project)
    engine = get_engine()
    while True:
        try:
            with Session(engine) as session:
                if deliver_one(session, sender):
                    continue
        except SQLAlchemyError:
            logger.error("푸시 대기열을 처리할 수 없어 다시 연결합니다.")
        time.sleep(2)


if __name__ == "__main__":
    main()
