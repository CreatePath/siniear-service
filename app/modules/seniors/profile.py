from typing import Annotated, Literal
from uuid import UUID

from fastapi import Header
from pydantic import ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import select

from app.core.errors import DomainError
from app.core.schemas import Input, Interests, Name, Region
from app.db.models.identity import MediaAsset

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Avatar = Literal["default", "leaf"]
VersionHeader = Annotated[str, Header(pattern=r'^"[1-9][0-9]*"$', max_length=12)]


ActivityStyle = Literal["active", "calm", "social"]


class ProfileFields(Input):
    activity_style: ActivityStyle | None = None
    job_title: Name | None = None
    card_name_mode: Literal["nickname", "name"] = "nickname"
    age_band: Name | None = None
    avatar_key: Avatar = "default"
    photo_id: UUID | None = None
    experience: ShortText | None = None
    strengths: Interests = Field(default_factory=list)
    interests: Interests = Field(default_factory=list)
    can_share: Interests = Field(default_factory=list)
    want_to_learn: Interests = Field(default_factory=list)
    activity_goals: Interests = Field(default_factory=list)
    disposition: ShortText | None = None
    intro: ShortText | None = None


class ProfileCreate(ProfileFields):
    nickname: Name
    region_code: Region


class ProfileEdits(ProfileFields):
    nickname: Name | None = None
    region_code: Region | None = None

    @model_validator(mode="after")
    def required_values(self):
        for key in ("nickname", "region_code"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError("필수 항목은 지울 수 없습니다.")
        return self


class ProfilePatch(ProfileEdits):
    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("변경할 항목이 필요합니다.")
        return self


class Profile(ProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    name: str | None
    id: UUID
    user_id: UUID
    version: int


def check_photo(session, user_id, photo_id):
    if photo_id and not session.scalar(
        select(MediaAsset.id).where(
            MediaAsset.id == photo_id,
            MediaAsset.owner_user_id == user_id,
            MediaAsset.purpose == "profile_photo",
        )
    ):
        raise DomainError(422, "VALIDATION_ERROR", "본인이 등록한 프로필 사진을 선택해 주세요.")


def check_name(mode, verified_name):
    if mode == "name" and not verified_name:
        raise DomainError(422, "VALIDATION_ERROR", "인증된 이름이 필요합니다.")


def edit_profile(session, senior, edits, version):
    if senior.version != version:
        raise DomainError(409, "PROFILE_CHANGED", "프로필이 변경되었습니다.")
    values = edits.model_dump(exclude_unset=True)
    check_name(values.get("card_name_mode"), senior.name)
    check_photo(session, senior.user_id, values.get("photo_id"))
    for field, value in values.items():
        setattr(senior, field, value)
    senior.version += 1
