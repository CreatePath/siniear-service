from sqlalchemy import select

from app.core.errors import DomainError
from app.db.models.interview import Card
from app.modules.cards.schemas import CardPreview, CardView


def owned_card(session, senior_id, card_id, *, lock=False):
    query = select(Card).where(Card.id == card_id, Card.senior_id == senior_id)
    if lock:
        query = query.with_for_update()
    card = session.scalar(query)
    if card is None:
        raise DomainError(404, "CARD_NOT_FOUND", "명함을 찾을 수 없습니다.")
    return card


def changed():
    return DomainError(409, "CARD_CHANGED", "명함이 변경되었습니다.")


def project_card(card, senior):
    fields = {}
    for key in card.visible_fields:
        if key == "photo_url":
            if senior.photo_id:
                fields[key] = f"/api/me/profile-photos/{senior.photo_id}"
        else:
            value = getattr(senior, key)
            if value is not None:
                fields[key] = value
    name = senior.name if senior.card_name_mode == "name" and senior.name else senior.nickname
    return CardPreview(
        name=name, template_key=card.template_key, color_code=card.color_code, fields=fields
    )


def card_view(card, senior):
    return CardView(
        **project_card(card, senior).model_dump(),
        id=card.id,
        version=card.version,
        visible_fields=card.visible_fields,
    )
