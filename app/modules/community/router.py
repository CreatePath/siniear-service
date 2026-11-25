from uuid import UUID

from fastapi import APIRouter, Response

from app.api.dependencies import Actor, Cursor, Database, Key, Limit
from app.core.errors import API_ERRORS
from app.core.schemas import Page
from app.modules.community import service
from app.modules.community.schemas import (
    CommentResponse,
    CommentWrite,
    PostCreate,
    PostPatch,
    PostResponse,
)

router = APIRouter(tags=["community"], responses=API_ERRORS)


@router.get("/groups/{group_id}/posts", response_model=Page[PostResponse])
def posts(
    group_id: UUID, actor: Actor, session: Database, limit: Limit = 20, cursor: Cursor = None
):
    return service.list_posts(session, group_id, limit, cursor)


@router.post("/groups/{group_id}/posts", response_model=PostResponse, status_code=201)
def create_post(group_id: UUID, data: PostCreate, actor: Actor, session: Database):
    return service.create_post(session, actor, group_id, data)


@router.get("/posts/{post_id}", response_model=PostResponse)
def post(post_id: UUID, actor: Actor, session: Database):
    return service.read_post(session, post_id)


@router.patch("/posts/{post_id}", response_model=PostResponse)
def update_post(post_id: UUID, data: PostPatch, actor: Actor, session: Database):
    return service.update_post(session, actor, post_id, data)


@router.delete("/posts/{post_id}", status_code=204)
def delete_post(post_id: UUID, actor: Actor, session: Database):
    service.delete_post(session, actor, post_id)
    return Response(status_code=204)


@router.get("/posts/{post_id}/comments", response_model=Page[CommentResponse])
def comments(
    post_id: UUID, actor: Actor, session: Database, limit: Limit = 20, cursor: Cursor = None
):
    return service.list_comments(session, post_id, limit, cursor)


@router.post("/posts/{post_id}/comments", response_model=CommentResponse, status_code=201)
def create_comment(post_id: UUID, data: CommentWrite, actor: Actor, session: Database):
    return service.create_comment(session, actor, post_id, data)


@router.patch("/comments/{comment_id}", response_model=CommentResponse)
def update_comment(comment_id: UUID, data: CommentWrite, actor: Actor, session: Database):
    return service.update_comment(session, actor, comment_id, data)


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: UUID, actor: Actor, session: Database):
    service.delete_comment(session, actor, comment_id)
    return Response(status_code=204)


@router.get("/meetings/{meeting_id}/comments")
def meeting_comments(
    meeting_id: UUID, actor: Actor, session: Database, limit: Limit = 20, cursor: Cursor = None
) -> Page[CommentResponse]:
    return service.thread_page(session, actor, limit, cursor, meeting_id=meeting_id)


@router.post("/meetings/{meeting_id}/comments", status_code=201)
def add_meeting_comment(
    meeting_id: UUID, data: CommentWrite, key: Key, actor: Actor, session: Database
) -> CommentResponse:
    return service.write_thread(session, actor, data, key, meeting_id=meeting_id)


@router.get("/comments/{comment_id}/replies")
def replies(
    comment_id: UUID, actor: Actor, session: Database, limit: Limit = 20, cursor: Cursor = None
) -> Page[CommentResponse]:
    return service.thread_page(session, actor, limit, cursor, parent_id=comment_id)


@router.post("/comments/{comment_id}/replies", status_code=201)
def add_reply(
    comment_id: UUID, data: CommentWrite, key: Key, actor: Actor, session: Database
) -> CommentResponse:
    return service.write_thread(session, actor, data, key, parent_id=comment_id)
