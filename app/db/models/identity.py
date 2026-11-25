from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    kakao_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    access_hash: Mapped[str] = mapped_column(Text, unique=True)
    refresh_hash: Mapped[str] = mapped_column(Text, unique=True)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdentityVerification(Base):
    __tablename__ = "identity_verifications"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(Text, default="pending")
    provider_reference: Mapped[str | None] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Senior(Base):
    __tablename__ = "seniors"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(Text)
    phone_number: Mapped[str | None] = mapped_column(Text)
    region_code: Mapped[str] = mapped_column(Text)
    interests: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    call_agree: Mapped[bool] = mapped_column(Boolean, server_default="false")
    version: Mapped[int] = mapped_column(server_default="1")
    avatar_key: Mapped[str] = mapped_column(Text, server_default="default")
    photo_id: Mapped[UUID | None] = mapped_column(ForeignKey("media_assets.id"))
    age_band: Mapped[str | None] = mapped_column(Text)
    experience: Mapped[str | None] = mapped_column(Text)
    disposition: Mapped[str | None] = mapped_column(Text)
    intro: Mapped[str | None] = mapped_column(Text)
    strengths: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    can_share: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    want_to_learn: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    activity_goals: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")


class MediaAsset(Base):
    __tablename__ = "media_assets"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(Text)
    content: Mapped[bytes]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
