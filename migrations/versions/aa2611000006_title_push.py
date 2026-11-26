"""기기별 칭호 푸시 대기열. 이전에 획득한 칭호는 발송하지 않는다."""

from alembic import op

revision = "aa2611000006"
down_revision = "aa2611000005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE push_devices (
            session_id uuid PRIMARY KEY REFERENCES refresh_sessions(id) ON DELETE CASCADE,
            token text NOT NULL CONSTRAINT uq_push_devices_token UNIQUE
        );
        CREATE TABLE title_push_deliveries (
            session_id uuid NOT NULL REFERENCES push_devices(session_id) ON DELETE CASCADE,
            title_id uuid NOT NULL REFERENCES membership_titles(id) ON DELETE CASCADE,
            attempts integer NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (session_id, title_id)
        );
        CREATE INDEX ix_title_push_due ON title_push_deliveries(next_attempt_at);
    """)


def downgrade():
    op.drop_table("title_push_deliveries")
    op.drop_table("push_devices")
