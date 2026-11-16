from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, StringConstraints

from app.core.schemas import Input, Name, Patch

PostContent = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
]
CommentContent = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]


class PostCreate(Input):
    title: Name
    content: PostContent


class PostPatch(Patch):
    title: Name | None = None
    content: PostContent | None = None


class CommentWrite(Input):
    content: CommentContent


class PostResponse(BaseModel):
    id: UUID
    group_id: UUID
    author_id: UUID
    author_name: str
    title: str
    content: str
    comment_count: int
    created_at: datetime
    updated_at: datetime


class CommentResponse(BaseModel):
    id: UUID
    post_id: UUID
    author_id: UUID
    author_name: str
    content: str
    created_at: datetime
    updated_at: datetime
