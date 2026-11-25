from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Interview(Base):
    __tablename__ = "interviews"
    __table_args__ = (
        CheckConstraint("status IN ('active','ready','confirmed')", name="status"),
        CheckConstraint("version > 0 AND profile_version > 0", name="version"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    senior_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"), index=True)
    status: Mapped[str] = mapped_column(Text, default="active")
    next_question: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    draft: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    version: Mapped[int] = mapped_column(default=1)
    profile_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InterviewTurn(Base):
    __tablename__ = "interview_turns"
    __table_args__ = (
        UniqueConstraint("interview_id", "seq"),
        CheckConstraint("skipped = (answer IS NULL)", name="answer_or_skip"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    interview_id: Mapped[UUID] = mapped_column(ForeignKey("interviews.id", ondelete="CASCADE"))
    seq: Mapped[int]
    question: Mapped[dict] = mapped_column(JSONB)
    answer: Mapped[str | None] = mapped_column(Text)
    skipped: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("version > 0", name="version"),
        Index(
            "uq_personal_card",
            "senior_id",
            unique=True,
            postgresql_where=text("membership_id IS NULL"),
        ),
        ForeignKeyConstraint(
            ["membership_id", "senior_id"], ["group_memberships.id", "group_memberships.senior_id"]
        ),
        ForeignKeyConstraint(
            ["selected_title_id", "membership_id"],
            ["membership_titles.id", "membership_titles.membership_id"],
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    senior_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"))
    membership_id: Mapped[UUID | None] = mapped_column(unique=True)
    selected_title_id: Mapped[UUID | None]
    role: Mapped[str | None] = mapped_column(Text)
    group_intro: Mapped[str | None] = mapped_column(Text)
    color_code: Mapped[str] = mapped_column(Text, server_default="#1D961B")
    template_key: Mapped[str] = mapped_column(Text)
    visible_fields: Mapped[list[str]] = mapped_column(ARRAY(Text))
    version: Mapped[int] = mapped_column(default=1)
