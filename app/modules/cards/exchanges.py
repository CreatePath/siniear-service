from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response
from sqlalchemy import and_, any_, case, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from app.api.dependencies import Actor, Cursor, Database, Key, Limit
from app.core.errors import API_ERRORS, DomainError
from app.core.idempotency import remember, replay
from app.core.pagination import paginate
from app.core.schemas import Page
from app.db.models import Group, Senior
from app.db.models.exchange import Exchange, ExchangeOffer, Favorite
from app.db.models.identity import MediaAsset
from app.db.models.interview import Card
from app.db.models.membership import Membership
from app.modules.cards.exchange_schemas import (
    Accept,
    BookItem,
    BookPage,
    ExchangeView,
    OfferCreated,
    OfferInput,
    Preview,
    Scan,
    Star,
)
from app.modules.cards.service import active_card, lock_cards, missing, owned_card, render_card
from app.modules.groups.activity_titles import record_exchange

router = APIRouter(tags=["card-exchanges"], responses=API_ERRORS)
OFFER_TTL = timedelta(minutes=10)


def connections(senior_id):
    """Orient each live pair for the current viewer."""
    mine = aliased(Card)
    peer = aliased(Card)
    return (
        select(
            Exchange.id.label("exchange_id"),
            mine.id.label("my_id"),
            peer.id.label("peer_id"),
            Exchange.exchanged_at,
            Exchange.exchange_method,
        )
        .select_from(Exchange)
        .join(mine, or_(mine.id == Exchange.card_low_id, mine.id == Exchange.card_high_id))
        .join(
            peer,
            peer.id
            == case(
                (mine.id == Exchange.card_low_id, Exchange.card_high_id), else_=Exchange.card_low_id
            ),
        )
        .where(mine.senior_id == senior_id, active_card(mine), active_card(peer))
        .subquery()
    )


def exchange_view(session, row):
    return ExchangeView(
        id=row.exchange_id,
        my_card_id=row.my_id,
        peer_card=render_card(session, session.get(Card, row.peer_id)),
        exchanged_at=row.exchanged_at,
        exchange_method=row.exchange_method,
    )


def available_offer(session, token, *, lock=False):
    query = select(ExchangeOffer).where(
        ExchangeOffer.token_hash == sha256(token.encode()).hexdigest()
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    offer = session.scalar(query)
    if offer is None or offer.consumed_at or offer.expires_at <= datetime.now(UTC):
        raise DomainError(409, "OFFER_UNAVAILABLE", "사용할 수 없는 교환 제안입니다.")
    return offer


def offered_card(session, offer, actor):
    card = session.scalar(select(Card).where(Card.id == offer.card_id, active_card()))
    if card is None:
        raise DomainError(409, "OFFER_UNAVAILABLE", "사용할 수 없는 교환 제안입니다.")
    if card.senior_id == actor.senior_id:
        raise DomainError(409, "SELF_EXCHANGE", "본인과는 교환할 수 없습니다.")
    return card


@router.post("/exchange-offers", status_code=201)
def offer(data: OfferInput, actor: Actor, session: Database, response: Response) -> OfferCreated:
    with session.begin():
        owned_card(session, actor.senior_id, data.card_id, lock=True)
        token = token_urlsafe(32)
        row = ExchangeOffer(
            card_id=data.card_id,
            token_hash=sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + OFFER_TTL,
        )
        session.add(row)
        session.flush()
        response.headers["Cache-Control"] = "no-store"
        return OfferCreated(offer_id=row.id, token=token, expires_at=row.expires_at)


@router.post("/exchange-offers/preview")
def preview(data: Scan, actor: Actor, session: Database) -> Preview:
    with session.begin():
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        offer = available_offer(session, data.token)
        card = offered_card(session, offer, actor)
        return Preview(
            card=render_card(session, card, preview_offer=offer.id), expires_at=offer.expires_at
        )


@router.post("/exchanges", status_code=201, responses={200: {"model": ExchangeView}})
def accept(
    data: Accept, key: Key, actor: Actor, session: Database, response: Response
) -> ExchangeView:
    args = ("C", str(actor.senior_id), "exchange.accept", key, data.model_dump())
    with session.begin():
        record = replay(session, *args)
        live = connections(actor.senior_id)
        if record:
            exchange = session.get(Exchange, record.resource_id)
            if exchange is None:
                raise missing()
            lock_cards(session, [exchange.card_low_id, exchange.card_high_id])
            result = session.execute(
                select(live).where(live.c.exchange_id == record.resource_id)
            ).one_or_none()
            if result is None:
                raise missing()
            response.status_code = record.http_status
            return exchange_view(session, result)
        offer = available_offer(session, data.token)
        lock_cards(session, [data.card_id, offer.card_id])
        offer = available_offer(session, data.token, lock=True)
        peer = offered_card(session, offer, actor)
        mine = session.scalar(select(Card).where(Card.id == data.card_id, active_card()))
        if mine is None:
            raise missing()
        if mine.senior_id != actor.senior_id:
            raise DomainError(403, "FORBIDDEN", "본인 명함을 선택해 주세요.")
        low, high = sorted([mine.id, peer.id])
        exchange = session.scalar(
            select(Exchange).where(Exchange.card_low_id == low, Exchange.card_high_id == high)
        )
        status = 200
        if exchange is None:
            exchange = Exchange(
                card_low_id=low,
                card_high_id=high,
                exchange_method=data.exchange_method,
                exchanged_at=datetime.now(UTC),
            )
            session.add(exchange)
            status = 201
        offer.consumed_at = datetime.now(UTC)
        session.flush()
        if status == 201:
            for card in (mine, peer):
                if card.membership_id:
                    record_exchange(session, card.membership_id, exchange.id)
        remember(session, *args, status, {}, resource_id=exchange.id)
        response.status_code = status
        return exchange_view(
            session, session.execute(select(live).where(live.c.exchange_id == exchange.id)).one()
        )


@router.get("/me/exchanges")
def exchanges(
    actor: Actor, session: Database, limit: Limit = 20, cursor: Cursor = None
) -> Page[ExchangeView]:
    with session.begin():
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        live = connections(actor.senior_id)
        rows, after = paginate(
            session,
            select(live),
            column=live.c.exchanged_at,
            id_column=live.c.exchange_id,
            limit=limit,
            cursor=cursor,
            scope=["exchanges", actor.senior_id],
            descending=True,
            mappings=True,
        )
        return Page(items=[exchange_view(session, row) for row in rows], next_cursor=after)


def book_entries(senior_id, keyword=""):
    live = connections(senior_id)
    rank = (
        func.row_number()
        .over(
            partition_by=live.c.peer_id,
            order_by=(live.c.exchanged_at.desc(), live.c.exchange_id.desc()),
        )
        .label("position")
    )
    latest = select(live, rank).subquery()
    star = (
        select(Favorite.received_card_id)
        .where(Favorite.owner_senior_id == senior_id, Favorite.received_card_id == latest.c.peer_id)
        .exists()
    )
    query = select(latest, star.label("is_favorite")).where(latest.c.position == 1)
    if keyword:
        name = case(
            (Senior.card_name_mode == "name", func.coalesce(Senior.name, Senior.nickname)),
            else_=Senior.nickname,
        )
        query = (
            query.join(Card, Card.id == latest.c.peer_id)
            .join(Senior, Senior.id == Card.senior_id)
            .outerjoin(Membership, Membership.id == Card.membership_id)
            .outerjoin(Group, Group.id == Membership.group_id)
            .where(
                or_(
                    name.icontains(keyword, autoescape=True),
                    Group.name.icontains(keyword, autoescape=True),
                    and_(
                        any_(Card.visible_fields) == "experience",
                        Senior.experience.icontains(keyword, autoescape=True),
                    ),
                )
            )
        )
    return query.subquery()


def book_item(session, row):
    return BookItem(
        peer_card=render_card(session, session.get(Card, row.peer_id)),
        exchanged_at=row.exchanged_at,
        exchange_method=row.exchange_method,
        is_favorite=row.is_favorite,
    )


def received(session, senior_id, card_id):
    book = book_entries(senior_id)
    row = session.execute(select(book).where(book.c.peer_id == card_id)).one_or_none()
    if row is None:
        raise missing()
    return row


@router.get("/me/card-book")
def book(
    actor: Actor,
    session: Database,
    keyword: Annotated[
        str,
        Query(
            max_length=200,
            description="명함 표시 이름, 소속 명함의 모임 이름, 공개된 경험 부분 검색",
        ),
    ] = "",
    favorite_only: bool = False,
    limit: Limit = 20,
    cursor: Cursor = None,
) -> BookPage:
    with session.begin():
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        keyword = keyword.strip()
        entries = book_entries(actor.senior_id, keyword)
        total, stars = session.execute(
            select(func.count(), func.count().filter(entries.c.is_favorite)).select_from(entries)
        ).one()
        query = select(entries)
        if favorite_only:
            query = query.where(entries.c.is_favorite)
        rows, after = paginate(
            session,
            query,
            column=entries.c.exchanged_at,
            id_column=entries.c.peer_id,
            limit=limit,
            cursor=cursor,
            scope=["card_book", actor.senior_id, keyword, favorite_only],
            descending=True,
            mappings=True,
        )
        return BookPage(
            items=[book_item(session, row) for row in rows],
            total_count=total,
            favorite_count=stars,
            next_cursor=after,
        )


@router.get("/me/card-book/{card_id}")
def entry(card_id: UUID, actor: Actor, session: Database) -> BookItem:
    with session.begin():
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        return book_item(session, received(session, actor.senior_id, card_id))


@router.put("/me/card-book/{card_id}/favorite")
def favorite(card_id: UUID, data: Star, actor: Actor, session: Database) -> Star:
    with session.begin():
        row = received(session, actor.senior_id, card_id)
        lock_cards(session, [row.my_id, card_id])
        received(session, actor.senior_id, card_id)
        if data.is_favorite:
            session.execute(
                insert(Favorite)
                .values(owner_senior_id=actor.senior_id, received_card_id=card_id)
                .on_conflict_do_nothing()
            )
        else:
            session.execute(
                delete(Favorite).where(
                    Favorite.owner_senior_id == actor.senior_id,
                    Favorite.received_card_id == card_id,
                )
            )
        return data


def photo_response(session, card):
    senior = session.get(Senior, card.senior_id)
    if "photo_url" not in card.visible_fields or not senior.photo_id:
        raise missing()
    image = session.get(MediaAsset, senior.photo_id)
    return Response(
        image.content, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"}
    )


@router.get("/cards/{card_id}/photo", response_class=Response)
def card_photo(card_id: UUID, actor: Actor, session: Database):
    with session.begin():
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        received(session, actor.senior_id, card_id)
        return photo_response(session, session.get(Card, card_id))


@router.get("/exchange-offers/{offer_id}/photo", response_class=Response)
def offer_photo(
    offer_id: UUID,
    actor: Actor,
    session: Database,
    x_exchange_token: Annotated[str, Header(max_length=256)],
):
    with session.begin():
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        offer = available_offer(session, x_exchange_token)
        if offer.id != offer_id:
            raise missing()
        return photo_response(session, offered_card(session, offer, actor))
