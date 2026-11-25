from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from app.api.dependencies import Actor, Database
from app.core.errors import API_ERRORS, DomainError
from app.core.pagination import paginate
from app.core.schemas import Page
from app.db.models.identity import Senior
from app.db.models.interview import Card
from app.db.models.membership import MembershipTitle
from app.modules.cards.exchanges import received
from app.modules.cards.schemas import CardPatch, CardSettings, CardView, OwnedView, PeerView
from app.modules.cards.service import active_card, changed, missing, owned_card, render_card
from app.modules.seniors.profile import VersionHeader

router = APIRouter(tags=["cards"], responses=API_ERRORS)


@router.get("/me/cards")
def list_cards(
    actor: Actor,
    session: Database,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[OwnedView]:
    with session.begin():
        rows, after = paginate(
            session,
            select(Card).where(Card.senior_id == actor.senior_id, active_card()),
            column=Card.id,
            id_column=Card.id,
            limit=limit,
            cursor=cursor,
            scope=["personal_cards", str(actor.senior_id)],
        )
        return Page(
            items=[render_card(session, card, owner=True) for card in rows], next_cursor=after
        )


@router.get("/cards/{card_id}")
def detail(card_id: UUID, actor: Actor, session: Database) -> OwnedView | PeerView:
    with session.begin():
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        card = session.scalar(select(Card).where(Card.id == card_id, active_card()))
        if card is None:
            raise missing()
        if card.senior_id != actor.senior_id:
            received(session, actor.senior_id, card_id)
        return render_card(session, card, owner=card.senior_id == actor.senior_id)


@router.patch("/cards/{card_id}")
def update(
    card_id: UUID, data: CardPatch, if_match: VersionHeader, actor: Actor, session: Database
) -> OwnedView:
    with session.begin():
        card = owned_card(session, actor.senior_id, card_id, lock=True)
        if card.version != int(if_match[1:-1]):
            raise changed()
        group_only = {"role", "group_intro", "selected_title_id"}
        if card.membership_id is None and (
            data.model_fields_set & group_only
            or set(data.visible_fields or []) & {"role", "group_intro", "title"}
        ):
            raise DomainError(422, "VALIDATION_ERROR", "소속 명함에서만 사용할 수 있습니다.")
        if data.selected_title_id and not session.scalar(
            select(MembershipTitle.id).where(
                MembershipTitle.id == data.selected_title_id,
                MembershipTitle.membership_id == card.membership_id,
            )
        ):
            raise DomainError(422, "VALIDATION_ERROR", "현재 소속에서 보유한 칭호를 선택해 주세요.")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(card, key, value)
        card.version += 1
        return render_card(session, card, owner=True)


@router.post("/me/cards", status_code=201)
def create_personal(data: CardSettings, actor: Actor, session: Database) -> CardView:
    with session.begin():
        session.get(Senior, actor.senior_id, with_for_update=True)
        if session.scalar(
            select(Card.id).where(Card.senior_id == actor.senior_id, Card.membership_id.is_(None))
        ):
            raise DomainError(409, "CARD_EXISTS", "개인 명함이 이미 있습니다.")
        card = Card(senior_id=actor.senior_id, **data.model_dump())
        session.add(card)
        session.flush()
        return render_card(session, card, owner=True)


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: UUID, if_match: VersionHeader, actor: Actor, session: Database):
    with session.begin():
        card = owned_card(session, actor.senior_id, card_id, lock=True)
        if card.version != int(if_match[1:-1]):
            raise changed()
        if card.membership_id:
            raise DomainError(409, "MEMBERSHIP_CARD", "소속 명함은 모임 탈퇴 시 종료됩니다.")
        session.delete(card)
        return Response(status_code=204)
