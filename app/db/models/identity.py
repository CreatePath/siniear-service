from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


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
    phone_number: Mapped[str] = mapped_column(Text)
    region_code: Mapped[str] = mapped_column(Text)
    interests: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    call_agree: Mapped[bool] = mapped_column(Boolean)
