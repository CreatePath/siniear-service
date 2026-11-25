from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExchangeOffer(Base):
    __tablename__ = "exchange_offers"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    card_id: Mapped[UUID] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Exchange(Base):
    __tablename__ = "card_exchanges"
    __table_args__ = (
        UniqueConstraint("card_low_id", "card_high_id"),
        CheckConstraint("card_low_id < card_high_id", name="sorted_pair"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    card_low_id: Mapped[UUID] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    card_high_id: Mapped[UUID] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    exchanged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    exchange_method: Mapped[str | None] = mapped_column(Text)


class Favorite(Base):
    __tablename__ = "card_book_favorites"
    owner_senior_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"), primary_key=True)
    received_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
