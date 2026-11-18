from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, field_validator

from app.core.schemas import Input, Patch

Weekday = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
Days = Annotated[list[Weekday], Field(min_length=1, max_length=7)]
ClockTime = Annotated[str, StringConstraints(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]
CallStatus = Literal[
    "queued",
    "initiated",
    "ringing",
    "in_progress",
    "completed",
    "busy",
    "no_answer",
    "failed",
    "canceled",
]


class ScheduleCreate(Input):
    days_of_week: Days
    local_time: ClockTime
    timezone: Literal["Asia/Seoul"]
    enabled: bool

    @field_validator("days_of_week")
    @classmethod
    def unique_days(cls, value):
        return list(dict.fromkeys(value))


class SchedulePatch(Patch):
    days_of_week: Days | None = None
    local_time: ClockTime | None = None
    timezone: Literal["Asia/Seoul"] | None = None
    enabled: bool | None = None


class ScheduleResponse(BaseModel):
    id: UUID
    senior_id: UUID
    days_of_week: list[str]
    local_time: str
    timezone: str = "Asia/Seoul"
    enabled: bool
    next_call_at: datetime | None


class CallResponse(BaseModel):
    id: UUID
    senior_id: UUID
    episode_id: UUID
    attempt_no: int
    direction: str = "outbound"
    status: CallStatus
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None
    summary_status: str
    indexing_status: str
    transcript_status: str
    provider_call_id: str | None


class SummaryResponse(BaseModel):
    call_id: UUID
    summary: str
    created_at: datetime


class CallDetail(CallResponse):
    summary: SummaryResponse | None


class StateEvent(Input):
    event_id: str = Field(min_length=1, max_length=200)
    occurred_at: AwareDatetime
    provider_call_id: str | None = Field(default=None, min_length=1, max_length=100)
    provider_sequence: int | None = Field(default=None, ge=0)
    status: CallStatus
