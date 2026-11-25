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


def get_comment_for_change(session, comment_id):
    post_id = session.scalar(select(Comment.post_id).where(Comment.id == comment_id))
    if post_id is None:
        raise DomainError(404, "COMMENT_NOT_FOUND", "댓글을 찾을 수 없습니다.")
    # All comment changes take the parent lock first, including physical deletion.
    post = get_post(session, post_id, lock=True)
    comment = session.get(Comment, comment_id, populate_existing=True)
    if comment is None:
        raise DomainError(404, "COMMENT_NOT_FOUND", "댓글을 찾을 수 없습니다.")
    return post, comment


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
            .where(Comment.post_id.in_([row.id for row in rows]))
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
    return [
        CommentResponse(
            id=row.id,
            post_id=row.post_id,
            author_id=row.author_id,
            author_name=names[row.author_id],
            content=row.content,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
