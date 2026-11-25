from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool, StringConstraints

from app.core.schemas import Input, Name, Patch

Phone = Annotated[str, StringConstraints(pattern=r"^\+[1-9][0-9]{7,14}$")]


class ContactCreate(Input):
    name: Name
    phone_number: Phone


class ContactPatch(Patch):
    name: Name | None = None
    phone_number: Phone | None = None
    enabled: StrictBool | None = None


class Contact(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    senior_id: UUID
    name: str
    phone_number: str
    enabled: bool


class Contacts(BaseModel):
    items: list[Contact]
