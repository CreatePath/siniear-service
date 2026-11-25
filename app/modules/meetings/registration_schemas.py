from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.meetings.schemas import MeetingResponse


class RegistrationResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    senior_id: UUID
    status: Literal["confirmed", "canceled"]
    version: int
    created_at: datetime
    updated_at: datetime


class RegistrationWithMeeting(RegistrationResponse):
    meeting: MeetingResponse
