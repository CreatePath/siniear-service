from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StrictBool

from app.core.schemas import Input, Page
from app.modules.cards.schemas import PeerView

Token = Annotated[str, Field(min_length=1, max_length=256)]
Method = Literal["qr"]


class OfferInput(Input):
    card_id: UUID


class Scan(Input):
    token: Token


class Accept(Scan):
    card_id: UUID
    exchange_method: Method | None = None


class OfferCreated(BaseModel):
    offer_id: UUID
    token: str
    expires_at: datetime


class Preview(BaseModel):
    card: PeerView
    expires_at: datetime


class ExchangeView(BaseModel):
    id: UUID
    my_card_id: UUID
    peer_card: PeerView
    exchanged_at: datetime
    exchange_method: Method | None


class BookItem(BaseModel):
    peer_card: PeerView
    exchanged_at: datetime
    exchange_method: Method | None
    is_favorite: bool


class BookPage(Page[BookItem]):
    total_count: int
    favorite_count: int


class Star(Input):
    is_favorite: StrictBool
