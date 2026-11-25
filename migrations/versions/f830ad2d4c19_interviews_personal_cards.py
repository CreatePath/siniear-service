"""앱 인터뷰, 문답과 개인 명함."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "f830ad2d4c19"
down_revision = "e327f104a9bd"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "interviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("senior_id", sa.Uuid(), sa.ForeignKey("seniors.id"), nullable=False, index=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("next_question", JSONB()),
        sa.Column("draft", JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('active','ready','confirmed')", name="status"),
        sa.CheckConstraint("version > 0 AND profile_version > 0", name="version"),
    )
    op.create_table(
        "interview_turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "interview_id",
            sa.Uuid(),
            sa.ForeignKey("interviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("question", JSONB(), nullable=False),
        sa.Column("answer", sa.Text()),
        sa.Column("skipped", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("interview_id", "seq"),
        sa.CheckConstraint("skipped = (answer IS NULL)", name="answer_or_skip"),
    )
    op.create_table(
        "cards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("senior_id", sa.Uuid(), sa.ForeignKey("seniors.id"), nullable=False, unique=True),
        sa.Column("template_key", sa.Text(), nullable=False),
        sa.Column("visible_fields", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("version > 0", name="version"),
    )


def downgrade():
    op.drop_table("cards")
    op.drop_table("interview_turns")
    op.drop_table("interviews")
