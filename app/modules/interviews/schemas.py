from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.schemas import Input, Interests, Name
from app.modules.seniors.profile import ActivityStyle, ShortText


class Question(Input):
    key: Name
    kind: Literal["main", "follow_up"]
    text: ShortText


class Draft(Input):
    activity_style: ActivityStyle | None = None
    experience: ShortText | None = None
    strengths: Interests = Field(default_factory=list)
    interests: Interests = Field(default_factory=list)
    can_share: Interests = Field(default_factory=list)
    want_to_learn: Interests = Field(default_factory=list)
    activity_goals: Interests = Field(default_factory=list)
    disposition: ShortText | None = None
    intro: ShortText | None = None


class InterviewView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: Literal["active", "ready", "confirmed"]
    version: int
    profile_version: int
    next_question: Question | None
    draft: Draft | None


class Answer(Input):
    version: int = Field(gt=0)
    question_key: Name
    answer: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
        | None
    ) = None
    skip: bool = False

    @model_validator(mode="after")
    def one_answer(self):
        if self.skip == (self.answer is not None):
            raise ValueError("답변을 입력하거나 건너뛰기를 선택해 주세요.")
        return self
