from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Region = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
Description = Annotated[str, StringConstraints(max_length=5000)]
Interest = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Interests = Annotated[list[Interest], Field(max_length=20)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Patch(Input):
    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set or any(
            getattr(self, k) is None for k in self.model_fields_set
        ):
            raise ValueError("Provide at least one non-null field")
        return self


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None
