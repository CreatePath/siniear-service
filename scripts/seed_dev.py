"""합성 계정만 추가한다. 기존 프로필·인증 결과는 수정하지 않는다."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import IdentityVerification, Senior, User
from app.db.session import get_engine

ACCOUNTS = ("owner", "member", "other", "unverified")


def ids(name):
    return (
        uuid5(NAMESPACE_URL, f"siniear:dev:user:{name}"),
        uuid5(NAMESPACE_URL, f"siniear:dev:senior:{name}"),
    )


def seed(session):
    for index, name in enumerate(ACCOUNTS):
        user_id, senior_id = ids(name)
        # An existing account may have deliberately changed state; never restore it.
        if session.get(User, user_id) is not None:
            continue
        session.add(User(id=user_id))
        session.flush()
        session.add(
            Senior(
                id=senior_id,
                user_id=user_id,
                name=f"가상회원{index + 1}",
                region_code="11110",
                interests=["산책", "독서"],
            )
        )
        if name != "unverified":
            session.add(
                IdentityVerification(
                    user_id=user_id, status="verified", verified_at=datetime.now(UTC)
                )
            )
    session.flush()


def main():
    settings = get_settings()
    if settings.app_env not in {"development", "test"}:
        raise SystemExit("seed requires APP_ENV=development or test")
    with Session(get_engine()) as session, session.begin():
        seed(session)
    for name in ACCOUNTS:
        user_id, senior_id = ids(name)
        print(f"{name}: user_id={user_id} senior_id={senior_id}")


if __name__ == "__main__":
    main()
