from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.schemas import Input, Name
from app.modules.seniors.profile import Profile, ProfileEdits, ShortText

Template = Literal["default", "classic", "fresh_start"]
Color = Literal["#F02820", "#2062D1", "#1D961B", "#8D49CF", "#E64C94"]
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
    "job_title",
    "region_code",
]
GroupField = Literal["role", "group_intro", "title"]
VisibleFields = Annotated[list[PublicField], Field(max_length=13)]
GroupFields = Annotated[list[PublicField | GroupField], Field(max_length=16)]


class CardSettings(Input):
    template_key: Template
    color_code: Color = "#1D961B"
    visible_fields: VisibleFields

    @field_validator("visible_fields")
    @classmethod
    def distinct_fields(cls, value):
        if value is not None and len(value) != len(set(value)):
            raise ValueError("공개 항목이 중복되었습니다.")
        return value


class CardPatch(CardSettings):
    template_key: Template | None = None
    visible_fields: GroupFields | None = None
    role: Name | None = None
    group_intro: ShortText | None = None
    selected_title_id: UUID | None = None

    @model_validator(mode="after")
    def changes(self):
        if not self.model_fields_set or any(
            getattr(self, k) is None
            for k in self.model_fields_set & {"template_key", "visible_fields"}
        ):
            raise ValueError("변경할 명함 설정을 입력해 주세요.")
        return self


class CardPreview(BaseModel):
    kind: Literal["personal"] = "personal"
    name: str
    template_key: Template
    color_code: Color
    fields: dict[str, str | list[str]]


class PublicCard(CardPreview):
    id: UUID


class GroupInfo(BaseModel):
    id: UUID
    name: str
    badge_url: str | None
    joined_at: datetime


class PublicGroupCard(PublicCard):
    kind: Literal["group"] = "group"
    group: GroupInfo


class CardView(PublicCard):
    version: int
    visible_fields: VisibleFields


class GroupCardView(PublicGroupCard):
    version: int
    visible_fields: GroupFields
    membership_id: UUID
    selected_title_id: UUID | None
    role: str | None
    group_intro: str | None


OwnedView = GroupCardView | CardView
PeerView = PublicGroupCard | PublicCard


class Confirmation(CardSettings):
    version: int = Field(gt=0)
    profile_version: int = Field(gt=0)
    card_version: Annotated[int, Field(gt=0)] | None
    profile: ProfileEdits


class Confirmed(BaseModel):
    interview_id: UUID
    profile: Profile
    card: CardView
