from datetime import datetime, time
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CALL_STATES = (
    "'queued','initiated','ringing','in_progress','completed','bu"
    "sy','no_answer','failed','canceled'"
)
PROCESS_STATES = "'pending','processing','completed','failed','not_applicable'"


class CareContact(Base):
    __tablename__ = "care_contacts"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    senior_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    phone_number: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CallSchedule(Base):
    __tablename__ = "call_schedules"
    __table_args__ = (
        CheckConstraint("cardinality(days_of_week) BETWEEN 1 AND 7", name="days"),
        CheckConstraint(
            "days_of_week <@ ARRAY['MON','TUE','WED','THU','FRI','SAT','SUN']::text[]",
            name="weekdays",
        ),
        CheckConstraint(
            "(enabled AND deleted_at IS NULL) OR next_call_at IS NULL", name="inactive"
        ),
        Index("ix_call_schedules_due", "next_call_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    senior_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"), index=True)
    days_of_week: Mapped[list[str]] = mapped_column(ARRAY(Text))
    local_time: Mapped[time] = mapped_column(Time)
    enabled: Mapped[bool] = mapped_column(Boolean)
    next_call_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CallEpisode(Base):
    __tablename__ = "call_episodes"
    __table_args__ = (UniqueConstraint("schedule_id", "scheduled_at"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    schedule_id: Mapped[UUID] = mapped_column(ForeignKey("call_schedules.id"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Call(Base):
    __tablename__ = "calls"
    __table_args__ = (
        UniqueConstraint("episode_id", "attempt_no"),
        CheckConstraint("attempt_no BETWEEN 1 AND 3", name="attempt"),
        CheckConstraint(f"status IN ({CALL_STATES})", name="status"),
        CheckConstraint(
            "transcript_status IN ('pending','complete','partial','unavailable')", name="transcript"
        ),
        CheckConstraint(f"summary_status IN ({PROCESS_STATES})", name="summary_status"),
        CheckConstraint(f"indexing_status IN ({PROCESS_STATES})", name="indexing_status"),
        CheckConstraint("(summary IS NULL) = (summary_created_at IS NULL)", name="summary_pair"),
        CheckConstraint(
            "summary_status != 'completed' OR summary IS NOT NULL", name="summary_completed"
        ),
        CheckConstraint(
            (
                "(embedding IS NULL AND embedding_model_id IS NULL AND "
                "embedding_source_hash IS NULL) OR (embedding IS NOT NULL "
                "AND embedding_model_id IS NOT NULL AND "
                "embedding_source_hash IS NOT NULL AND "
                "cardinality(embedding)=768)"
            ),
            name="embedding",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    episode_id: Mapped[UUID] = mapped_column(ForeignKey("call_episodes.id"))
    attempt_no: Mapped[int]
    status: Mapped[str] = mapped_column(Text, default="queued")
    provider_call_id: Mapped[str | None] = mapped_column(Text, unique=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transcript_status: Mapped[str] = mapped_column(Text, default="pending")
    summary_status: Mapped[str] = mapped_column(Text, default="pending")
    indexing_status: Mapped[str] = mapped_column(Text, default="pending")
    summary: Mapped[str | None] = mapped_column(Text)
    summary_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Double))
    embedding_model_id: Mapped[str | None] = mapped_column(Text)
    embedding_source_hash: Mapped[str | None] = mapped_column(Text)


class TranscriptTurn(Base):
    __tablename__ = "transcript_turns"
    __table_args__ = (
        CheckConstraint("speaker IN ('user','assistant')", name="speaker"),
        CheckConstraint("offset_ms >= 0", name="offset"),
        Index("ix_transcript_turns_order", "call_id", "offset_ms", "turn_id"),
    )
    call_id: Mapped[UUID] = mapped_column(ForeignKey("calls.id"), primary_key=True)
    turn_id: Mapped[str] = mapped_column(Text, primary_key=True)
    speaker: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    offset_ms: Mapped[int]
    action_context: Mapped[dict | None] = mapped_column(JSONB)


class EmergencyAlert(Base):
    __tablename__ = "emergency_alerts"
    __table_args__ = (
        CheckConstraint(
            (
                "call_id != first_no_answer_call_id AND call_id != "
                "second_no_answer_call_id AND first_no_answer_call_id != "
                "second_no_answer_call_id"
            ),
            name="distinct_calls",
        ),
        CheckConstraint(
            "status IN ('pending','contacting','completed','failed','canceled')", name="status"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    call_id: Mapped[UUID] = mapped_column(ForeignKey("calls.id"), unique=True)
    first_no_answer_call_id: Mapped[UUID] = mapped_column(ForeignKey("calls.id"))
    second_no_answer_call_id: Mapped[UUID] = mapped_column(ForeignKey("calls.id"))
    status: Mapped[str] = mapped_column(Text, default="pending")
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    __table_args__ = (
        UniqueConstraint("alert_id", "contact_id"),
        CheckConstraint(f"status IN ({CALL_STATES})", name="status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    alert_id: Mapped[UUID] = mapped_column(ForeignKey("emergency_alerts.id"))
    contact_id: Mapped[UUID] = mapped_column(ForeignKey("care_contacts.id"))
    status: Mapped[str] = mapped_column(Text, default="queued")
    provider_call_id: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
