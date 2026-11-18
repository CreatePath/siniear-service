from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Registration(Base):
    __tablename__ = "meeting_registrations"
    __table_args__ = (
        UniqueConstraint("meeting_id", "senior_id"),
        CheckConstraint("status IN ('confirmed','canceled')", name="status"),
        CheckConstraint("version >= 1", name="version"),
        Index("ix_registrations_meeting_status", "meeting_id", "status"),
        Index("ix_registrations_senior_status", "senior_id", "status", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id"))
    senior_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"))
    status: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1)
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id"))


class RegistrationAction(Base):
    __tablename__ = "registration_actions"
    __table_args__ = (
        CheckConstraint("action IN ('register','cancel')", name="action"),
        CheckConstraint("resulting_version >= 1", name="version"),
        CheckConstraint("(call_id IS NULL) = (confirmation_turn_id IS NULL)", name="phone_pair"),
        ForeignKeyConstraint(
            [("call_id"), ("confirmation_turn_id")],
            [("transcript_turns.call_id"), ("transcript_turns.turn_id")],
        ),
        UniqueConstraint("call_id", "confirmation_turn_id"),
    )
    registration_id: Mapped[UUID] = mapped_column(
        ForeignKey("meeting_registrations.id"), primary_key=True
    )
    resulting_version: Mapped[int] = mapped_column(primary_key=True)
    actor_senior_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"))
    action: Mapped[str] = mapped_column(Text)
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id"))
    confirmation_turn_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("owner_service", "subject_id", "operation", "key"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_service: Mapped[str] = mapped_column(Text, default="C")
    subject_id: Mapped[str] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(Text)
    http_status: Mapped[int]
    response_body: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CancellationNotice(Base):
    """P9 전달용 대기. 발송 성공이나 사용자 확인을 의미하지 않는다."""

    __tablename__ = "cancellation_notices"
    __table_args__ = (
        UniqueConstraint("meeting_id", "recipient_senior_id", "kind"),
        CheckConstraint("kind IN ('meeting_canceled','organizer_phone_guidance')", name="kind"),
        CheckConstraint("state = 'pending'", name="pending_only"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meetings.id"))
    recipient_senior_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"))
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(Text, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
