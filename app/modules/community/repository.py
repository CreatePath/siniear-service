from sqlalchemy import func, select

from app.core.errors import DomainError
from app.db.models import Comment, Post, Senior
from app.modules.community.schemas import CommentResponse, PostResponse


def get_post(session, post_id, *, lock=False):
    query = select(Post).where(Post.id == post_id, Post.deleted_at.is_(None))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    post = session.scalar(query)
    if post is None:
        raise DomainError(404, "POST_NOT_FOUND", "게시글을 찾을 수 없습니다.")
    return post


def get_comment_for_change(session, comment_id, principal, *, lock=True):
    from app.modules.meetings.repository import get_meeting, require_meeting_access

    targets = session.execute(
        select(Comment.post_id, Comment.meeting_id).where(Comment.id == comment_id)
    ).one_or_none()
    if targets is None:
        raise DomainError(404, "COMMENT_NOT_FOUND", "댓글을 찾을 수 없습니다.")
    if targets.post_id:
        target = get_post(session, targets.post_id, lock=lock)
    else:
        target, _ = get_meeting(session, targets.meeting_id, lock=lock)
        require_meeting_access(session, target, principal.senior_id)
    comment = session.get(Comment, comment_id, populate_existing=True)
    if comment is None:
        raise DomainError(404, "COMMENT_NOT_FOUND", "댓글을 찾을 수 없습니다.")
    return target, comment


def author_names(session, rows):
    return dict(
        session.execute(
            select(Senior.id, Senior.nickname).where(Senior.id.in_({row.author_id for row in rows}))
        ).all()
    )


def post_responses(session, rows):
    if not rows:
        return []
    names = author_names(session, rows)
    counts = dict(
        session.execute(
            select(Comment.post_id, func.count(Comment.id))
            .where(
                Comment.post_id.in_([row.id for row in rows]), Comment.parent_comment_id.is_(None)
            )
            .group_by(Comment.post_id)
        ).all()
    )
    return [
        PostResponse(
            id=row.id,
            group_id=row.group_id,
            author_id=row.author_id,
            author_name=names[row.author_id],
            title=row.title,
            content=row.content,
            comment_count=counts.get(row.id, 0),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


def comment_responses(session, rows):
    if not rows:
        return []
    names = author_names(session, rows)
    counts = dict(
        session.execute(
            select(Comment.parent_comment_id, func.count())
            .where(Comment.parent_comment_id.in_([row.id for row in rows]))
            .group_by(Comment.parent_comment_id)
        ).all()
    )
    return [
        CommentResponse(
            id=row.id,
            post_id=row.post_id,
            meeting_id=row.meeting_id,
            parent_comment_id=row.parent_comment_id,
            reply_count=counts.get(row.id, 0),
            author_id=row.author_id,
            author_name=names[row.author_id],
            content=row.content,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
