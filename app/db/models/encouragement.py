from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tag(StrEnum):
    kind = "kind"
    sociable = "sociable"
    dependable = "dependable"
    admirable = "admirable"
    responsible = "responsible"
    fun = "fun"
    comforting = "comforting"
    positive = "positive"
    warmhearted = "warmhearted"


class Encouragement(Base):
    __tablename__ = "encouragement_messages"
    __table_args__ = (
        UniqueConstraint("meeting_id", "author_id", "recipient_id"),
        CheckConstraint("author_id <> recipient_id", name="different_members"),
        CheckConstraint("version > 0", name="version"),
        Index(
            "ix_encouragement_inbox",
            "recipient_id",
            "created_at",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id"))
    author_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"))
    recipient_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"))
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageTag(Base):
    __tablename__ = "encouragement_message_tags"
    __table_args__ = (
        CheckConstraint(
            "tag IN (" + ", ".join(repr(t.value) for t in Tag) + ")", name="allowed_tag"
        ),
    )
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("encouragement_messages.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(Text, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EncouragementReport(Base):
    __tablename__ = "encouragement_reports"
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("encouragement_messages.id", ondelete="CASCADE"), primary_key=True
    )
    reporter_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
