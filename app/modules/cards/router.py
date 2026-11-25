from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.dependencies import Actor, Database
from app.core.errors import API_ERRORS
from app.core.pagination import paginate
from app.core.schemas import Page
from app.db.models.identity import Senior
from app.db.models.interview import Card
from app.modules.cards.schemas import CardPatch, CardView
from app.modules.cards.service import card_view, changed, owned_card
from app.modules.seniors.profile import VersionHeader

router = APIRouter(tags=["cards"], responses=API_ERRORS)


@router.get("/me/cards")
def list_cards(
    actor: Actor,
    session: Database,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[CardView]:
    with session.begin():
        rows, after = paginate(
            session,
            select(Card).where(Card.senior_id == actor.senior_id),
            column=Card.id,
            id_column=Card.id,
            limit=limit,
            cursor=cursor,
            scope=["personal_cards", str(actor.senior_id)],
        )
        senior = session.get(Senior, actor.senior_id)
        return Page(items=[card_view(card, senior) for card in rows], next_cursor=after)


@router.get("/cards/{card_id}")
def detail(card_id: UUID, actor: Actor, session: Database) -> CardView:
    with session.begin():
        card = owned_card(session, actor.senior_id, card_id)
        return card_view(card, session.get(Senior, actor.senior_id))


@router.patch("/cards/{card_id}")
def update(
    card_id: UUID, data: CardPatch, if_match: VersionHeader, actor: Actor, session: Database
) -> CardView:
    with session.begin():
        card = owned_card(session, actor.senior_id, card_id, lock=True)
        if card.version != int(if_match[1:-1]):
            raise changed()
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(card, key, value)
        card.version += 1
        return card_view(card, session.get(Senior, actor.senior_id))
