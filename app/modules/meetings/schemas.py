from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.schemas import Description, Input, Name, Patch, Region

Location = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Capacity = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
MeetingStatus = Literal["recruiting", "closed", "canceled", "completed"]
ActivityCategory = Literal["walk", "hobby", "exercise"]


class MeetingCreate(Input):
    title: Name
    category: ActivityCategory | None = None
    description: Description = ""
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    location: Location
    capacity: Capacity
    registration_closes_at: AwareDatetime

    @model_validator(mode="after")
    def time_order(self):
        if self.ends_at <= self.starts_at or self.registration_closes_at > self.starts_at:
            raise ValueError("Invalid meeting time order")
        return self


class IndependentMeetingCreate(MeetingCreate):
    region_code: Region
    group_id: None = None


class MeetingPatch(Patch):
    title: Name | None = None
    category: ActivityCategory | None = None
    description: Description | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    location: Location | None = None
    capacity: Capacity | None = None
    registration_closes_at: AwareDatetime | None = None
    region_code: Region | None = None
    status: Literal["recruiting", "closed", "canceled"] | None = None
    cancel_reason: Reason | None = None

    @model_validator(mode="after")
    def cancellation(self):
        if (self.status == "canceled") != (self.cancel_reason is not None):
            raise ValueError("Cancellation requires a reason")
        if self.status == "canceled" and self.model_fields_set != {"status", "cancel_reason"}:
            raise ValueError("Cancellation must be submitted separately")
        return self


class MeetingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    group_id: UUID | None
    owner_id: UUID
    region_code: str
    title: str
    category: ActivityCategory | None = None
    description: str
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    location: str
    capacity: int
    registration_closes_at: AwareDatetime
    status: MeetingStatus
    comment_count: int = 0
    participant_count: int = 0
    remaining_capacity: int = 0
