from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.schemas import Description, Input, Interests, Name, Patch, Region


class GroupCreate(Input):
    name: Name
    description: Description = ""
    region_code: Region
    interests: Interests = Field(default_factory=list)


class GroupPatch(Patch):
    name: Name | None = None
    description: Description | None = None
    region_code: Region | None = None
    interests: Interests | None = None
    status: Literal["closed"] | None = None


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    owner_id: UUID
    name: str
    description: str
    region_code: str
    interests: list[str]
    status: Literal["active", "closed"]
    created_at: datetime
