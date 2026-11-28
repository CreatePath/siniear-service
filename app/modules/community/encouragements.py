from collections import defaultdict
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import DomainError
from app.core.idempotency import remember, replay
from app.core.pagination import paginate
from app.db.models import Group, Meeting, Registration
from app.db.models.encouragement import Encouragement, EncouragementReport, MessageTag, Tag
from app.db.models.exchange import Exchange
from app.db.models.interview import Card
from app.db.models.membership import Membership
from app.modules.community.encouragement_schemas import Inbox, MessageView, TagCount
from app.modules.meetings.repository import accessible_groups, get_meeting
from app.modules.meetings.service import now

CREATE = "encouragement.create"


def missing():
    return DomainError(404, "ENCOURAGEMENT_NOT_FOUND", "응원 메시지를 찾을 수 없습니다.")


def eligible_recipient(session, meeting_id, author_id, *, card_id=None, recipient_id=None):
    meeting, group = get_meeting(session, meeting_id, lock=True)
    denied = DomainError(
        403,
        "ENCOURAGEMENT_FORBIDDEN",
        "서로 소속 명함을 교환하고 같은 일정에 신청한 회원만 응원할 수 있습니다.",
    )
    if not group or group.status != "active" or meeting.status == "canceled":
        raise denied
    cards = (
        select(Card.id, Card.senior_id)
        .join(Membership, Membership.id == Card.membership_id)
        .where(Membership.group_id == group.id, Membership.left_at.is_(None))
    )
    peer_filter = Card.id == card_id if card_id is not None else Card.senior_id == recipient_id
    peer = session.execute(cards.where(peer_filter)).one_or_none()
    mine = session.scalar(cards.where(Card.senior_id == author_id))
    if peer is None or mine is None or peer.senior_id == author_id:
        raise denied
    low, high = sorted([mine, peer.id])
    exchanged = session.scalar(
        select(Exchange.id).where(Exchange.card_low_id == low, Exchange.card_high_id == high)
    )
    confirmed = session.scalar(
        select(func.count())
        .select_from(Registration)
        .where(
            Registration.meeting_id == meeting.id,
            Registration.status == "confirmed",
            Registration.senior_id.in_([author_id, peer.senior_id]),
        )
    )
    if not exchanged or confirmed != 2:
        raise denied
    return meeting, peer.senior_id


def check_window(ends_at, at):
    if not ends_at <= at <= ends_at + timedelta(hours=72):
        raise DomainError(
            409,
            "ENCOURAGEMENT_WINDOW_CLOSED",
            "일정 종료 후 3일 이내에 작성하거나 수정할 수 있습니다.",
        )


def message_views(session, messages):
    if not messages:
        return []
    tags = defaultdict(list)
    for mid, tag in session.execute(
        select(MessageTag.message_id, MessageTag.tag)
        .where(MessageTag.message_id.in_([m.id for m in messages]))
        .order_by(MessageTag.tag)
    ):
        tags[mid].append(tag)
    return [
        MessageView(
            id=m.id,
            meeting_id=m.meeting_id,
            tags=tags[m.id],
            text=m.text,
            created_at=m.created_at,
            version=m.version,
        )
        for m in messages
    ]


def create(session, author_id, meeting_id, data, key):
    with session.begin():
        args = ("C", str(author_id), CREATE, key, {"meeting_id": meeting_id, **data.model_dump()})
        cached = replay(session, *args)
        meeting, recipient = eligible_recipient(
            session, meeting_id, author_id, card_id=data.recipient_card_id
        )
        if cached:
            message = session.get(Encouragement, cached.resource_id)
            if not message or message.deleted_at:
                raise missing()
            return message_views(session, [message])[0]
        at = now()
        check_window(meeting.ends_at, at)
        if session.scalar(
            select(Encouragement.id).where(
                Encouragement.meeting_id == meeting_id,
                Encouragement.author_id == author_id,
                Encouragement.recipient_id == recipient,
            )
        ):
            raise DomainError(
                409, "ENCOURAGEMENT_EXISTS", "이 일정에서 이미 응원을 보낸 회원입니다."
            )
        message = Encouragement(
            meeting_id=meeting_id,
            author_id=author_id,
            recipient_id=recipient,
            text=data.text,
            created_at=at,
        )
        session.add(message)
        session.flush()
        session.add_all(MessageTag(message_id=message.id, tag=t, received_at=at) for t in data.tags)
        remember(session, *args, 201, {}, resource_id=message.id)
        return message_views(session, [message])[0]


def authored(session, message_id, author_id):
    message = session.scalar(
        select(Encouragement)
        .where(Encouragement.id == message_id, Encouragement.author_id == author_id)
        .with_for_update()
    )
    if not message:
        raise missing()
    return message


def edit(session, message_id, author_id, version, data):
    with session.begin():
        message = authored(session, message_id, author_id)
        if message.deleted_at:
            raise missing()
        if message.version != version:
            raise DomainError(409, "ENCOURAGEMENT_CHANGED", "응원 메시지가 변경되었습니다.")
        meeting, _ = eligible_recipient(
            session, message.meeting_id, author_id, recipient_id=message.recipient_id
        )
        at = now()
        check_window(meeting.ends_at, at)
        tags = MessageTag.__table__
        session.execute(
            delete(MessageTag).where(
                MessageTag.message_id == message.id, MessageTag.tag.not_in(data.tags)
            )
        )
        session.execute(
            insert(tags)
            .values([{"message_id": message.id, "tag": t, "received_at": at} for t in data.tags])
            .on_conflict_do_nothing()
        )
        message.text = data.text
        message.version += 1
        return message_views(session, [message])[0]


def remove(session, message_id, author_id):
    with session.begin():
        message = authored(session, message_id, author_id)
        if message.deleted_at is None:
            message.deleted_at = now()


def report(session, message_id, recipient_id):
    with session.begin():
        message = session.scalar(
            select(Encouragement.id)
            .where(
                Encouragement.id == message_id,
                Encouragement.recipient_id == recipient_id,
                Encouragement.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if not message:
            raise missing()
        session.execute(
            insert(EncouragementReport)
            .values(message_id=message_id, reporter_id=recipient_id)
            .on_conflict_do_nothing()
        )


def received_messages(group_id, recipient_id):
    return (
        select(Encouragement)
        .join(Meeting, Meeting.id == Encouragement.meeting_id)
        .where(
            Meeting.group_id == group_id,
            Encouragement.recipient_id == recipient_id,
            Encouragement.deleted_at.is_(None),
        )
    )


def tag_totals(session, group_id, recipient_id):
    count = func.count(MessageTag.message_id)
    query = received_messages(group_id, recipient_id).join(
        MessageTag, MessageTag.message_id == Encouragement.id
    )
    return session.execute(
        query.with_only_columns(MessageTag.tag, count)
        .group_by(MessageTag.tag)
        .order_by(count.desc(), func.max(MessageTag.received_at).desc(), MessageTag.tag)
    ).all()


def inbox(session, group_id, recipient_id, limit, cursor):
    with session.begin():
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        if not session.scalar(
            select(Group.id).where(
                Group.id == group_id,
                Group.status == "active",
                Group.id.in_(accessible_groups(recipient_id)),
            )
        ):
            raise DomainError(
                403, "MEMBERSHIP_REQUIRED", "가입한 동호회의 받은 응원을 조회할 수 있습니다."
            )
        rows, after = paginate(
            session,
            received_messages(group_id, recipient_id),
            column=Encouragement.created_at,
            id_column=Encouragement.id,
            limit=limit,
            cursor=cursor,
            descending=True,
            scope=["received_encouragements", group_id, recipient_id],
        )
        totals = dict(tag_totals(session, group_id, recipient_id))
        return Inbox(
            items=message_views(session, rows),
            next_cursor=after,
            tag_counts=[TagCount(tag=t, count=totals.get(t, 0)) for t in Tag],
        )
