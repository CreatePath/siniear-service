"""전화 없이 테스트할 공유 가상 데이터. stdin으로 runtime 이미지에서도 실행 가능."""

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Comment,
    Group,
    IdentityVerification,
    Meeting,
    Post,
    Registration,
    RegistrationAction,
    User,
)
from app.db.session import get_engine

ACCOUNTS = ("owner", "member", "other", "unverified")


def demo_id(kind, name):
    return uuid5(NAMESPACE_URL, f"siniear:non-call-demo:v1:{kind}:{name}")


def manifest():
    return {
        "accounts": {
            name: {
                "user_id": str(demo_id("user", name)),
                "senior_id": str(demo_id("senior", name)),
                "swagger_token": f"dev:{demo_id('user', name)}",
            }
            for name in ACCOUNTS
        },
        "groups": {name: str(demo_id("group", name)) for name in ("walk", "books")},
        "meetings": {
            name: str(demo_id("meeting", name)) for name in ("walk", "full", "solo", "past")
        },
        "registrations": {
            name: str(demo_id("registration", name)) for name in ("member-walk", "other-full")
        },
        "posts": {name: str(demo_id("post", name)) for name in ("notice", "hello", "books")},
    }


def seed(session, now=None):
    """호출자가 단일 트랜잭션을 소유한다. 완료된 배치는 재생성/갱신하지 않는다."""
    session.execute(text("SELECT pg_advisory_xact_lock(7390106)"))
    user_ids = [demo_id("user", name) for name in ACCOUNTS]
    existing = set(session.scalars(select(User.id).where(User.id.in_(user_ids))))
    if existing:
        if existing != set(user_ids):
            raise ValueError("가상 계정 일부만 존재합니다. 자동 복원하지 않으므로 DB를 확인하세요.")
        return False

    now = now or datetime.now(UTC)
    base = now.astimezone(ZoneInfo("Asia/Seoul")).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    # Older community schemas require these fields when importing a demo before upgrading.
    seniors = Table("seniors", MetaData(), autoload_with=session.connection(), resolve_fks=False)
    legacy_defaults = {"phone_number": "", "call_agree": False} if "call_agree" in seniors.c else {}
    for name in ACCOUNTS:
        session.execute(User.__table__.insert().values(id=demo_id("user", name)))
        session.execute(
            seniors.insert().values(
                id=demo_id("senior", name),
                user_id=demo_id("user", name),
                **{"nickname" if "nickname" in seniors.c else "name": f"테스트회원-{name}"},
                region_code="11110",
                interests=["산책", "독서"],
                **legacy_defaults,
            )
        )
        if name != "unverified":
            session.add(
                IdentityVerification(
                    id=demo_id("verification", name),
                    user_id=demo_id("user", name),
                    status="verified",
                    provider_reference=f"synthetic:non-call-demo:{name}",
                    verified_at=now,
                )
            )
    session.flush()

    for name, title, interest in (
        ("walk", "[테스트] 동네 산책 모임", "산책"),
        ("books", "[테스트] 함께 읽는 독서 모임", "독서"),
    ):
        session.execute(
            Group.__table__.insert()
            .inline()
            .values(
                id=demo_id("group", name),
                owner_id=demo_id("senior", "owner"),
                name=title,
                description="팀 공동 테스트용 가상 모임입니다.",
                region_code="11110",
                interests=[interest],
                status="active",
            )
        )
    session.flush()

    if "nickname" in seniors.c and session.scalar(
        text("SELECT to_regclass('group_memberships') IS NOT NULL")
    ):
        from app.modules.groups.repository import issue_membership

        for group_name in ("walk", "books"):
            issue_membership(session, demo_id("group", group_name), demo_id("senior", "owner"), now)

    for name, title, group, days, capacity in (
        ("walk", "[테스트] 참가 신청 가능한 산책", "walk", 7, 10),
        ("full", "[테스트] 정원이 찬 독서 모임", "books", 10, 1),
        ("solo", "[테스트] 그룹 없는 독립 모임", None, 14, 5),
        ("past", "[테스트] 종료된 지난 산책", "walk", -7, 10),
    ):
        starts_at = base + timedelta(days=days)
        session.add(
            Meeting(
                id=demo_id("meeting", name),
                group_id=demo_id("group", group) if group else None,
                owner_id=demo_id("senior", "owner"),
                region_code="11110",
                title=title,
                description="실제 행사가 아닌 API 테스트 일정입니다.",
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=1),
                registration_closes_at=starts_at - timedelta(hours=1),
                location="가상 테스트 장소",
                capacity=capacity,
                status="completed" if days < 0 else "recruiting",
            )
        )
    session.flush()

    for account, meeting in (("member", "walk"), ("other", "full")):
        registration_id = demo_id("registration", f"{account}-{meeting}")
        session.add(
            Registration(
                id=registration_id,
                meeting_id=demo_id("meeting", meeting),
                senior_id=demo_id("senior", account),
                status="confirmed",
                version=1,
            )
        )
        session.flush()
        session.add(
            RegistrationAction(
                registration_id=registration_id,
                resulting_version=1,
                actor_senior_id=demo_id("senior", account),
                action="register",
                created_at=now,
            )
        )

    for name, group, author, title in (
        ("notice", "walk", "owner", "[테스트] 산책 모임 안내"),
        ("hello", "walk", "member", "[테스트] 참가 인사"),
        ("books", "books", "other", "[테스트] 다음에 읽을 책"),
    ):
        session.add(
            Post(
                id=demo_id("post", name),
                group_id=demo_id("group", group),
                author_id=demo_id("senior", author),
                title=title,
                content="게시글 조회·수정·삭제를 확인하는 합성 데이터입니다.",
            )
        )
    session.flush()
    for name, post, author in (
        ("welcome", "notice", "member"),
        ("reply", "hello", "owner"),
        ("book-reply", "books", "member"),
    ):
        session.execute(
            Comment.__table__.insert()
            .inline()
            .values(
                id=demo_id("comment", name),
                post_id=demo_id("post", post),
                author_id=demo_id("senior", author),
                content="댓글 권한과 수정·삭제를 확인하는 테스트 댓글입니다.",
            )
        )
    session.flush()
    return True


def main():
    settings = get_settings()
    if settings.app_env not in {"development", "test"}:
        raise SystemExit("APP_ENV=development 또는 test에서만 실행하세요.")
    if os.environ.get("SEED_NON_CALL_DEMO") != "1":
        raise SystemExit("SEED_NON_CALL_DEMO=1을 명시해야 실행합니다.")
    with Session(get_engine()) as session, session.begin():
        created = seed(session)
    print(json.dumps({"created": created, **manifest()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
