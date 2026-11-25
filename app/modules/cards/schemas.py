from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.schemas import Input, Patch
from app.modules.seniors.profile import Profile, ProfileEdits

Template = Literal["default", "classic"]
PublicField = Literal[
    "age_band",
    "avatar_key",
    "photo_url",
    "experience",
    "strengths",
    "interests",
    "can_share",
    "want_to_learn",
    "activity_goals",
    "disposition",
    "intro",
]
VisibleFields = Annotated[list[PublicField], Field(max_length=11)]


class CardSettings(Input):
    template_key: Template
    visible_fields: VisibleFields

    @field_validator("visible_fields")
    @classmethod
    def distinct_fields(cls, value):
        if value is not None and len(value) != len(set(value)):
            raise ValueError("공개 항목이 중복되었습니다.")
        return value


class CardPatch(CardSettings, Patch):
    template_key: Template | None = None
    visible_fields: VisibleFields | None = None


class CardPreview(BaseModel):
    kind: Literal["personal"] = "personal"
    name: str
    template_key: Template
    fields: dict[str, str | list[str]]


class CardView(CardPreview):
    id: UUID
    version: int
    visible_fields: VisibleFields


class Confirmation(CardSettings):
    version: int = Field(gt=0)
    profile_version: int = Field(gt=0)
    card_version: Annotated[int, Field(gt=0)] | None
    profile: ProfileEdits


class Confirmed(BaseModel):
    interview_id: UUID
    profile: Profile
    card: CardView
