"""커뮤니티 게시글과 댓글.

Revision ID: 7ac4d29b10ef
Revises: 4095cfc36d7d
"""

import sqlalchemy as sa
from alembic import op

revision = "7ac4d29b10ef"
down_revision = "4095cfc36d7d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "posts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(trim(title)) BETWEEN 1 AND 100", name="title_length"),
        sa.CheckConstraint("length(trim(content)) BETWEEN 1 AND 5000", name="content_length"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["author_id"], ["seniors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_posts_group_created",
        "posts",
        ["group_id", "created_at", "id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(trim(content)) BETWEEN 1 AND 1000", name="content_length"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.ForeignKeyConstraint(["author_id"], ["seniors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comments_post_created", "comments", ["post_id", "created_at", "id"])


def downgrade():
    op.drop_table("comments")
    op.drop_table("posts")
