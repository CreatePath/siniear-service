"""동호회 일정별 응원, 받은 태그와 신고."""

from alembic import op

revision = "aa2611000009"
down_revision = "aa2611000008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE encouragement_messages (
            id uuid PRIMARY KEY,
            meeting_id uuid NOT NULL REFERENCES meetings(id),
            author_id uuid NOT NULL REFERENCES seniors(id),
            recipient_id uuid NOT NULL REFERENCES seniors(id),
            text text,
            created_at timestamptz NOT NULL DEFAULT now(),
            version integer NOT NULL CHECK (version > 0),
            deleted_at timestamptz,
            CHECK (author_id <> recipient_id),
            CONSTRAINT uq_encouragement_messages_meeting_id
                UNIQUE (meeting_id, author_id, recipient_id)
        );
        CREATE INDEX ix_encouragement_inbox ON encouragement_messages(recipient_id, created_at, id)
            WHERE deleted_at IS NULL;
        CREATE TABLE encouragement_message_tags (
            message_id uuid NOT NULL REFERENCES encouragement_messages(id) ON DELETE CASCADE,
            tag text NOT NULL CHECK (tag IN (
                'kind','sociable','dependable','admirable','responsible',
                'fun','comforting','positive','warmhearted')),
            received_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (message_id, tag)
        );
        CREATE TABLE encouragement_reports (
            message_id uuid NOT NULL REFERENCES encouragement_messages(id) ON DELETE CASCADE,
            reporter_id uuid NOT NULL REFERENCES seniors(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (message_id, reporter_id)
        );
    """)


def downgrade():
    op.drop_table("encouragement_reports")
    op.drop_table("encouragement_message_tags")
    op.drop_table("encouragement_messages")
