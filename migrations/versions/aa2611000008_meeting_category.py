"""일정 검색용 활동 분류를 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "aa2611000008"
down_revision = "aa2611000007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("meetings", sa.Column("category", sa.Text(), nullable=True))
    op.create_check_constraint("category", "meetings", "category IN ('walk','hobby','exercise')")


def downgrade():
    op.drop_constraint(op.f("ck_meetings_category"), "meetings", type_="check")
    op.drop_column("meetings", "category")
