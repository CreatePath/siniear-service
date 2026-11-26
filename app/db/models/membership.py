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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Membership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        UniqueConstraint("id", "senior_id"),
        UniqueConstraint("id", "group_id", "senior_id", name="uq_membership_group_owner"),
        CheckConstraint("left_at >= joined_at", name="period"),
        Index(
            "uq_membership_active",
            "group_id",
            "senior_id",
            unique=True,
            postgresql_where=text("left_at IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[UUID] = mapped_column(ForeignKey("groups.id"))
    senior_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    post_count: Mapped[int] = mapped_column(server_default="0")
    exchange_count: Mapped[int] = mapped_column(server_default="0")


class JoinRequest(Base):
    __tablename__ = "group_join_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["membership_id", "group_id", "senior_id"],
            ["group_memberships.id", "group_memberships.group_id", "group_memberships.senior_id"],
        ),
        CheckConstraint(
            "status IN ('pending','approved','rejected','canceled')"
            " AND (status='approved')=(membership_id IS NOT NULL)"
            " AND (status='pending')=(resolved_at IS NULL)"
            " AND (status IN ('approved','rejected'))=(reviewed_by IS NOT NULL)"
            " AND resolved_at >= created_at",
            name="resolution",
        ),
        Index(
            "uq_join_pending",
            "group_id",
            "senior_id",
            unique=True,
            postgresql_where=text("status='pending'"),
        ),
        Index(
            "ix_join_queue",
            "group_id",
            "created_at",
            "id",
            postgresql_where=text("status='pending'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[UUID] = mapped_column(ForeignKey("groups.id"))
    senior_id: Mapped[UUID] = mapped_column(ForeignKey("seniors.id"))
    status: Mapped[str] = mapped_column(Text, default="pending")
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("seniors.id"))
    membership_id: Mapped[UUID | None] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActivityTitleRule(Base):
    __tablename__ = "activity_title_rules"
    __table_args__ = (
        UniqueConstraint("activity", "threshold"),
        CheckConstraint("tier IN ('silver','gold','diamond')", name="tier"),
        CheckConstraint("activity IN ('join','registration','post','exchange')", name="activity"),
        CheckConstraint("threshold > 0", name="threshold"),
    )
    label: Mapped[str] = mapped_column(Text, primary_key=True)
    tier: Mapped[str] = mapped_column(Text)
    activity: Mapped[str] = mapped_column(Text)
    threshold: Mapped[int]


class MembershipTitle(Base):
    __tablename__ = "membership_titles"
    __table_args__ = (
        UniqueConstraint("id", "membership_id"),
        UniqueConstraint("membership_id", "label"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    membership_id: Mapped[UUID] = mapped_column(ForeignKey("group_memberships.id"))
    label: Mapped[str] = mapped_column(Text)
    evidence_ref: Mapped[str] = mapped_column(Text)
