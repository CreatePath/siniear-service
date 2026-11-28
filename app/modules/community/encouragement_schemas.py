from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.schemas import Input, Page
from app.db.models.encouragement import Tag


class EncouragementWrite(Input):
    tags: list[Tag] = Field(min_length=1, max_length=len(Tag))
    text: str | None = None

    @field_validator("tags")
    @classmethod
    def distinct_tags(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("서로 다른 태그를 선택해 주세요.")
        return value


class EncouragementCreate(EncouragementWrite):
    recipient_card_id: UUID


class MessageView(BaseModel):
    id: UUID
    meeting_id: UUID
    tags: list[Tag]
    text: str | None
    created_at: datetime
    version: int


class TagCount(BaseModel):
    tag: Tag
    count: int


class Inbox(Page[MessageView]):
    tag_counts: list[TagCount]
