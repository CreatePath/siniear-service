"""보유 칭호의 이름을 티어가 지정된 기준표에 연결한다."""

from alembic import op

revision = "aa2611000007"
down_revision = "aa2611000006"
branch_labels = None
depends_on = None

constraint = "fk_membership_titles_label_activity_title_rules"


def upgrade():
    op.create_foreign_key(
        constraint,
        "membership_titles",
        "activity_title_rules",
        ["label"],
        ["label"],
        onupdate="CASCADE",
        ondelete="RESTRICT",
    )


def downgrade():
    op.drop_constraint(constraint, "membership_titles", type_="foreignkey")
