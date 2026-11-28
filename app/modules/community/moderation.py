"""신고된 응원 메시지 검토. 서비스 DB에 접근하는 운영자 전용 명령."""

import argparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.encouragement import Encouragement, EncouragementReport
from app.db.session import get_engine
from app.modules.community.encouragements import message_views
from app.modules.meetings.service import now


def moderate(session, action, message_id=None, version=None):
    reported = (
        select(EncouragementReport.message_id)
        .where(EncouragementReport.message_id == Encouragement.id)
        .exists()
    )
    query = select(Encouragement).where(reported, Encouragement.deleted_at.is_(None))
    if action == "list":
        return "\n".join(
            str(mid)
            for mid in session.scalars(
                query.with_only_columns(Encouragement.id).order_by(
                    Encouragement.created_at, Encouragement.id
                )
            )
        )
    query = query.where(Encouragement.id == message_id)
    message = session.scalar(query.with_for_update(read=action == "show"))
    if message is None:
        raise ValueError("검토할 신고 메시지가 없습니다.")
    if action == "show":
        return message_views(session, [message])[0].model_dump_json()
    if action != "delete" or message.version != version:
        raise ValueError("최신 메시지를 다시 검토하고 버전을 확인해 주세요.")
    message.deleted_at = now()
    return "삭제했습니다."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list")
    commands.add_parser("show").add_argument("message_id", type=UUID)
    remove = commands.add_parser("delete")
    remove.add_argument("message_id", type=UUID)
    remove.add_argument("--version", type=int, required=True)
    args = parser.parse_args()
    with Session(get_engine()) as session, session.begin():
        try:
            result = moderate(session, **vars(args))
        except ValueError as exc:
            parser.exit(1, f"{exc}\n")
    print(result)


if __name__ == "__main__":
    main()
