from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (
        CheckConstraint("status IN ('active','closed')", name="status"),
        Index("ix_groups_region_status_created", "region_code", "status", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    region_code: Mapped[str] = mapped_column(Text)
    interests: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    status: Mapped[str] = mapped_column(Text, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="capacity"),
        CheckConstraint("ends_at > starts_at", name="time_order"),
        CheckConstraint("registration_closes_at <= starts_at", name="deadline"),
        CheckConstraint("status IN ('recruiting','closed','canceled','completed')", name="status"),
        CheckConstraint(
            "status <> 'canceled' OR length(trim(cancel_reason)) > 0 AND cancel_reason IS NOT NULL",
            name="cancel_reason",
        ),
        Index("ix_meetings_region_status_starts", "region_code", "status", "starts_at", "id"),
        Index("ix_meetings_group_starts", "group_id", "starts_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[UUID | None] = mapped_column(ForeignKey("groups.id", ondelete="RESTRICT"))
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"))
    region_code: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location: Mapped[str] = mapped_column(Text)
    capacity: Mapped[int]
    registration_closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, default="recruiting")
    cancel_reason: Mapped[str | None] = mapped_column(Text)
