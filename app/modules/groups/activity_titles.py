from sqlalchemy import func, literal, select, update
from sqlalchemy.dialects.postgresql import insert

from app.db.models import Meeting, Registration, RegistrationAction, Senior
from app.db.models.identity import RefreshSession
from app.db.models.membership import ActivityTitleRule, Membership, MembershipTitle
from app.db.models.push import PushDevice, TitlePushDelivery


def award_titles(session, membership_id, activity, count, source_id):
    """The activity and its award commit together. Keep previously issued title IDs."""
    rules = select(
        func.gen_random_uuid(),
        literal(membership_id),
        ActivityTitleRule.label,
        literal(f"{activity}:{source_id}"),
    ).where(ActivityTitleRule.activity == activity, ActivityTitleRule.threshold == count)
    title_id = session.scalar(
        insert(MembershipTitle)
        .from_select(["id", "membership_id", "label", "evidence_ref"], rules)
        .on_conflict_do_nothing(index_elements=["membership_id", "label"])
        .returning(MembershipTitle.id)
    )
    if title_id is None:
        return
    devices = session.scalars(
        select(PushDevice.session_id)
        .join(RefreshSession, RefreshSession.id == PushDevice.session_id)
        .join(Senior, Senior.user_id == RefreshSession.user_id)
        .join(Membership, Membership.senior_id == Senior.id)
        .where(Membership.id == membership_id, RefreshSession.expires_at > func.now())
        .order_by(PushDevice.session_id)
        .with_for_update(of=PushDevice, read=True, key_share=True)
    )
    session.add_all(TitlePushDelivery(title_id=title_id, session_id=sid) for sid in devices)


def record_post(session, post):
    member = session.execute(
        update(Membership)
        .where(
            Membership.group_id == post.group_id,
            Membership.senior_id == post.author_id,
            Membership.joined_at <= post.created_at,
            Membership.left_at.is_(None),
        )
        .values(post_count=Membership.post_count + 1)
        .returning(Membership.id, Membership.post_count)
    ).one_or_none()
    if member:
        award_titles(session, member.id, "post", member.post_count, post.id)


def record_exchange(session, membership_id, exchange_id):
    # The caller holds both active cards and a shared lock on their groups.
    count = session.scalar(
        update(Membership)
        .where(Membership.id == membership_id)
        .values(exchange_count=Membership.exchange_count + 1)
        .returning(Membership.exchange_count)
    )
    award_titles(session, membership_id, "exchange", count, exchange_id)


def record_registration(session, group_id, registration):
    # Group registration holds the group lock through the new action and the award.
    member = session.scalars(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.senior_id == registration.senior_id,
            Membership.left_at.is_(None),
        )
    ).one()
    applied_in_period = (
        select(RegistrationAction.registration_id)
        .where(
            RegistrationAction.registration_id == Registration.id,
            RegistrationAction.action == "register",
            RegistrationAction.created_at >= member.joined_at,
        )
        .exists()
    )
    count = session.scalar(
        select(func.count())
        .select_from(Registration)
        .join(Meeting, Meeting.id == Registration.meeting_id)
        .where(
            Meeting.group_id == group_id,
            Registration.senior_id == member.senior_id,
            applied_in_period,
        )
    )
    award_titles(session, member.id, "registration", count, registration.id)
