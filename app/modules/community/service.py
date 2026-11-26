from datetime import UTC, datetime

from sqlalchemy import select

from app.core.errors import DomainError
from app.core.idempotency import remember, replay
from app.core.pagination import paginate
from app.core.schemas import Page
from app.db.models import Comment, Post
from app.modules.community.repository import (
    comment_responses,
    get_comment_for_change,
    get_post,
    post_responses,
)
from app.modules.groups.activity_titles import record_post
from app.modules.groups.repository import get_group
from app.modules.meetings.repository import get_meeting, require_meeting_access


def require_author(principal, author_id):
    if principal.senior_id != author_id:
        raise DomainError(403, "FORBIDDEN", "작성자만 수정할 수 있습니다.")


def require_delete_permission(session, principal, author_id, group_id):
    if principal.senior_id not in {author_id, get_group(session, group_id).owner_id}:
        raise DomainError(403, "FORBIDDEN", "작성자 또는 해당 모임장만 삭제할 수 있습니다.")


def list_posts(session, group_id, limit, cursor):
    with session.begin():
        get_group(session, group_id)
        rows, next_cursor = paginate(
            session,
            select(Post).where(Post.group_id == group_id, Post.deleted_at.is_(None)),
            column=Post.created_at,
            id_column=Post.id,
            limit=limit,
            cursor=cursor,
            descending=True,
            scope={"resource": "posts", "group_id": group_id},
        )
        return Page(items=post_responses(session, rows), next_cursor=next_cursor)


def read_post(session, post_id):
    with session.begin():
        return post_responses(session, [get_post(session, post_id)])[0]


def create_post(session, principal, group_id, data):
    with session.begin():
        # Establish the writing period in the same order as approvals and departures.
        get_group(session, group_id, lock=True)
        at = datetime.now(UTC)
        post = Post(
            group_id=group_id,
            author_id=principal.senior_id,
            created_at=at,
            updated_at=at,
            **data.model_dump(),
        )
        session.add(post)
        session.flush()
        record_post(session, post)
        return post_responses(session, [post])[0]


def update_post(session, principal, post_id, data):
    with session.begin():
        post = get_post(session, post_id, lock=True)
        require_author(principal, post.author_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(post, key, value)
        post.updated_at = datetime.now(UTC)
        session.flush()
        return post_responses(session, [post])[0]


def delete_post(session, principal, post_id):
    with session.begin():
        post = get_post(session, post_id, lock=True)
        require_delete_permission(session, principal, post.author_id, post.group_id)
        post.deleted_at = post.updated_at = datetime.now(UTC)


def list_comments(session, post_id, limit, cursor):
    with session.begin():
        get_post(session, post_id)
        rows, next_cursor = paginate(
            session,
            select(Comment)
            .join(Post)
            .where(
                Comment.post_id == post_id,
                Comment.parent_comment_id.is_(None),
                Post.deleted_at.is_(None),
            ),
            column=Comment.created_at,
            id_column=Comment.id,
            limit=limit,
            cursor=cursor,
            scope={"resource": "comments", "post_id": post_id},
        )
        return Page(items=comment_responses(session, rows), next_cursor=next_cursor)


def create_comment(session, principal, post_id, data):
    with session.begin():
        get_post(session, post_id, lock=True)
        now = datetime.now(UTC)
        comment = Comment(
            post_id=post_id,
            author_id=principal.senior_id,
            content=data.content,
            created_at=now,
            updated_at=now,
        )
        session.add(comment)
        session.flush()
        return comment_responses(session, [comment])[0]


def update_comment(session, principal, comment_id, data):
    with session.begin():
        _, comment = get_comment_for_change(session, comment_id, principal)
        require_author(principal, comment.author_id)
        comment.content = data.content
        comment.updated_at = datetime.now(UTC)
        session.flush()
        return comment_responses(session, [comment])[0]


def delete_comment(session, principal, comment_id):
    with session.begin():
        post, comment = get_comment_for_change(session, comment_id, principal)
        if comment.meeting_id:
            require_author(principal, comment.author_id)
        else:
            require_delete_permission(session, principal, comment.author_id, post.group_id)
        session.delete(comment)


def thread_target(session, actor, meeting_id, parent_id, lock):
    if parent_id is not None:
        _, parent = get_comment_for_change(session, parent_id, actor, lock=lock)
        if parent.parent_comment_id is not None:
            raise DomainError(422, "INVALID_REPLY_PARENT", "원댓글에만 답글을 달 수 있습니다.")
        return parent.post_id, parent.meeting_id
    meeting, _ = get_meeting(session, meeting_id, lock=lock)
    require_meeting_access(session, meeting, actor.senior_id)
    return None, meeting_id


def thread_page(session, actor, limit, cursor, *, meeting_id=None, parent_id=None):
    with session.begin():
        thread_target(session, actor, meeting_id, parent_id, False)
        query = select(Comment).where(Comment.parent_comment_id == parent_id)
        if meeting_id:
            query = query.where(Comment.meeting_id == meeting_id)
        rows, after = paginate(
            session,
            query,
            column=Comment.created_at,
            id_column=Comment.id,
            limit=limit,
            cursor=cursor,
            descending=parent_id is None,
            scope=["thread", actor.senior_id, meeting_id, parent_id],
        )
        return Page(items=comment_responses(session, rows), next_cursor=after)


def write_thread(session, actor, data, key, *, meeting_id=None, parent_id=None):
    args = (
        "C",
        str(actor.senior_id),
        "comment.write",
        key,
        {"meeting_id": meeting_id, "parent_id": parent_id, "content": data.content},
    )
    with session.begin():
        record = replay(session, *args)
        post_id, meeting_id = thread_target(session, actor, meeting_id, parent_id, True)
        if record:
            row = session.get(Comment, record.resource_id)
            if row is None:
                raise DomainError(404, "COMMENT_NOT_FOUND", "삭제된 댓글입니다.")
        else:
            row = Comment(
                post_id=post_id,
                meeting_id=meeting_id,
                parent_comment_id=parent_id,
                author_id=actor.senior_id,
                content=data.content,
            )
            session.add(row)
            session.flush()
            remember(session, *args, 201, {}, resource_id=row.id)
        return comment_responses(session, [row])[0]
