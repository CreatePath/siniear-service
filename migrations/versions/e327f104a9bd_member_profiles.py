"""비공개 회원 프로필과 프로필 사진."""

import sqlalchemy as sa
from alembic import op

revision = "e327f104a9bd"
down_revision = "d824e81c48c2"
branch_labels = None
depends_on = None

lists = ("strengths", "can_share", "want_to_learn", "activity_goals")
texts = ("age_band", "experience", "disposition", "intro")


def upgrade():
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True
        ),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.alter_column("seniors", "phone_number", nullable=True)
    op.alter_column("seniors", "call_agree", server_default=sa.false())
    for field in lists:
        op.add_column(
            "seniors", sa.Column(field, sa.ARRAY(sa.Text()), nullable=False, server_default="{}")
        )
    for field in texts:
        op.add_column("seniors", sa.Column(field, sa.Text()))
    op.add_column(
        "seniors", sa.Column("avatar_key", sa.Text(), nullable=False, server_default="default")
    )
    op.add_column("seniors", sa.Column("photo_id", sa.Uuid(), sa.ForeignKey("media_assets.id")))
    op.add_column("seniors", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    for field in (*lists, *texts, "avatar_key", "photo_id", "version"):
        op.drop_column("seniors", field)
    op.execute("UPDATE seniors SET phone_number='' WHERE phone_number IS NULL")
    op.alter_column("seniors", "phone_number", nullable=False)
    op.alter_column("seniors", "call_agree", server_default=None)
    op.drop_table("media_assets")
