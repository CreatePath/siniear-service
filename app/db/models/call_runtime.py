from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CallExecution(Base):
    __tablename__ = "call_executions"
    __table_args__ = (
        CheckConstraint(
            (
                "(call_id IS NOT NULL AND delivery_id IS NULL AND "
                "kind='check_in') OR (call_id IS NULL AND delivery_id IS NOT "
                "NULL AND kind='emergency')"
            ),
            name="target",
        ),
        CheckConstraint(
            "execution_status IN ('accepted','running','unknown','completed','failed')",
            name="status",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id"), unique=True)
    delivery_id: Mapped[UUID | None] = mapped_column(ForeignKey("alert_deliveries.id"), unique=True)
    kind: Mapped[str] = mapped_column(Text)
    request_payload: Mapped[dict] = mapped_column(JSONB)
    request_hash: Mapped[str] = mapped_column(Text)
    execution_status: Mapped[str] = mapped_column(Text, default="accepted")
    provider_call_id: Mapped[str | None] = mapped_column(Text, unique=True)
    provider_status: Mapped[str] = mapped_column(Text, default="queued")
    provider_sequence: Mapped[int] = mapped_column(default=-1)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stream_id: Mapped[str | None] = mapped_column(Text, unique=True)
    media_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        UniqueConstraint("producer_service", "dedupe_key"),
        Index("ix_outbox_messages_due", "producer_service", "state", "available_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    producer_service: Mapped[str] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(Text)
    resource_id: Mapped[UUID]
    dedupe_key: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(Text, default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class InboxEvent(Base):
    __tablename__ = "inbox_events"
    __table_args__ = (UniqueConstraint("consumer_service", "event_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    consumer_service: Mapped[str] = mapped_column(Text)
    event_id: Mapped[str] = mapped_column(Text)
    resource_id: Mapped[UUID]
    payload_hash: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CallProcessingJob(Base):
    __tablename__ = "call_processing_jobs"
    call_id: Mapped[UUID] = mapped_column(ForeignKey("calls.id"), primary_key=True)
    input_hash: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
