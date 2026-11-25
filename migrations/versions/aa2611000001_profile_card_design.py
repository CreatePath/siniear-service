"""프로필 닉네임과 인증 이름을 분리하고 명함 디자인을 보존한다."""

from alembic import op

revision = "aa2611000001"
down_revision = "1a65f02ce93b"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""UPDATE idempotency_records r SET resource_id=c.id
        FROM interviews i JOIN cards c ON c.senior_id=i.senior_id
        WHERE r.operation='interview.confirm' AND r.resource_id=i.id""")
    op.execute("ALTER TABLE seniors RENAME COLUMN name TO nickname")
    op.execute("""ALTER TABLE seniors ADD name text, ADD job_title text,
        ADD activity_style text CHECK (activity_style IN ('active','calm','social')),
        ADD card_name_mode text NOT NULL DEFAULT 'nickname'
        CHECK (card_name_mode IN ('nickname','name') AND (card_name_mode <> 'name' OR name IS NOT
            NULL))""")
    op.execute("""ALTER TABLE cards ADD color_code text NOT NULL DEFAULT '#1D961B'
        CHECK (color_code IN ('#F02820','#2062D1','#1D961B','#8D49CF','#E64C94')),
        ADD CHECK (template_key IN ('default','classic','fresh_start'))""")


def downgrade():
    raise RuntimeError("인증 이름과 명함 설정을 보존하려면 전환 전 백업을 복원하세요.")
