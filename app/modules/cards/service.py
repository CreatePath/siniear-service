from sqlalchemy import or_, select

from app.core.errors import DomainError
from app.db.models import Group, Senior
from app.db.models.interview import Card
from app.db.models.membership import Membership, MembershipTitle
from app.modules.cards.schemas import (
    CardPreview,
    CardView,
    GroupCardView,
    GroupInfo,
    PublicCard,
    PublicGroupCard,
)


def active_card(card=Card):
    return or_(
        card.membership_id.is_(None),
        select(Membership.id)
        .join(Group, Group.id == Membership.group_id)
        .where(
            Membership.id == card.membership_id,
            Membership.left_at.is_(None),
            Group.status == "active",
        )
        .exists(),
    )


def missing():
    return DomainError(404, "CARD_NOT_FOUND", "명함을 찾을 수 없습니다.")


def owned_card(session, senior_id, card_id, *, lock=False):
    query = select(Card).where(Card.id == card_id, Card.senior_id == senior_id, active_card())
    if lock:
        lock_cards(session, [card_id])
    card = session.scalar(query)
    if card is None:
        raise missing()
    return card


def changed():
    return DomainError(409, "CARD_CHANGED", "명함이 변경되었습니다.")


def project_card(card, senior, *, photo_url=None, group_fields=None):
    fields = {}
    for key in card.visible_fields:
        if key == "photo_url":
            value = photo_url or (
                f"/api/me/profile-photos/{senior.photo_id}" if senior.photo_id else None
            )
        elif key in {"role", "group_intro", "title"}:
            value = (group_fields or {}).get(key)
        else:
            value = getattr(senior, key)
        if value is not None:
            fields[key] = value
    name = senior.name if senior.card_name_mode == "name" and senior.name else senior.nickname
    return CardPreview(
        name=name, template_key=card.template_key, color_code=card.color_code, fields=fields
    )


def render_card(session, card, *, owner=False, preview_offer=None):
    senior = session.get(Senior, card.senior_id)
    extras = {}
    photo_url = None
    if senior.photo_id and not owner:
        photo_url = (
            f"/api/cards/{card.id}/photo"
            if not preview_offer
            else f"/api/exchange-offers/{preview_offer}/photo"
        )
    if card.membership_id:
        title = (
            session.get(MembershipTitle, card.selected_title_id) if card.selected_title_id else None
        )
        extras = {
            "role": card.role,
            "group_intro": card.group_intro,
            "title": title.label if title else None,
        }
    values = project_card(card, senior, photo_url=photo_url, group_fields=extras).model_dump()
    values["id"] = card.id
    if owner:
        values.update(version=card.version, visible_fields=card.visible_fields)
    if card.membership_id:
        if "title" in values["fields"] and title.tier is not None:
            values["fields"]["title_tier"] = title.tier
        membership = session.get(Membership, card.membership_id)
        group = session.get(Group, membership.group_id)
        values.update(
            kind="group",
            group=GroupInfo(
                id=group.id,
                name=group.name,
                badge_url=f"/api/groups/{group.id}/badge" if group.badge_id else None,
                joined_at=membership.joined_at,
            ),
        )
        if owner:
            return GroupCardView(
                **values,
                membership_id=membership.id,
                role=card.role,
                group_intro=card.group_intro,
                selected_title_id=card.selected_title_id,
                selected_title_tier=title.tier if title else None,
            )
        return PublicGroupCard(**values)
    return CardView(**values) if owner else PublicCard(**values)


def lock_cards(session, card_ids):
    # Membership changes lock their group. Use stable ordering for opposing exchanges.
    group_ids = (
        select(Membership.group_id)
        .join(Card, Card.membership_id == Membership.id)
        .where(Card.id.in_(card_ids))
    )
    session.scalars(
        select(Group.id)
        .where(Group.id.in_(group_ids))
        .order_by(Group.id)
        .with_for_update(read=True)
    ).all()
    session.scalars(
        select(Card.id).where(Card.id.in_(card_ids)).order_by(Card.id).with_for_update()
    ).all()
