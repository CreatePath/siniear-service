from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PushDevice(Base):
    __tablename__ = "push_devices"
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("refresh_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    token: Mapped[str] = mapped_column(Text, unique=True)


class TitlePushDelivery(Base):
    __tablename__ = "title_push_deliveries"
    __table_args__ = (Index("ix_title_push_due", "next_attempt_at"),)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("push_devices.session_id", ondelete="CASCADE"), primary_key=True
    )
    title_id: Mapped[UUID] = mapped_column(
        ForeignKey("membership_titles.id", ondelete="CASCADE"), primary_key=True
    )
    attempts: Mapped[int] = mapped_column(server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
