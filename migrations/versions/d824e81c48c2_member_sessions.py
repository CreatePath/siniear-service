"""카카오 계정 연결과 신이어 앱 세션."""

import sqlalchemy as sa
from alembic import op

revision = "d824e81c48c2"
down_revision = "c6a929f2dc12"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("kakao_user_id", sa.BigInteger(), unique=True))
    op.add_column("users", sa.Column("withdrawn_at", sa.DateTime(timezone=True)))
    op.add_column("idempotency_records", sa.Column("resource_id", sa.Uuid(), index=True))
    op.execute("""
        UPDATE idempotency_records i SET resource_id=m.resource_id FROM outbox_messages m
        WHERE i.owner_service='C' AND i.subject_id='T' AND i.operation='interests'
          AND m.producer_service='T' AND m.operation='call.interests' AND i.key=m.dedupe_key
    """)
    op.create_table(
        "refresh_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("access_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("refresh_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Both services use the same schema. Run the T-owned invalidation in the consent transaction.
    op.execute("""
        CREATE FUNCTION invalidate_member_search(member uuid) RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE targets uuid[];
        BEGIN
            SELECT ARRAY(SELECT c.id FROM calls c
                JOIN call_episodes e ON e.id = c.episode_id
                JOIN call_schedules s ON s.id = e.schedule_id
                WHERE s.senior_id = member) INTO targets;
            UPDATE call_processing_jobs SET state='canceled', lease_token=NULL, lease_until=NULL
                WHERE call_id=ANY(targets);
            UPDATE calls SET embedding=NULL, embedding_model_id=NULL, embedding_source_hash=NULL,
                indexing_status='not_applicable',
                summary_status=CASE WHEN summary IS NULL THEN 'not_applicable'
                                    ELSE summary_status END
                WHERE id=ANY(targets);
            UPDATE outbox_messages SET state='canceled', lease_token=NULL, lease_until=NULL
                WHERE producer_service='T' AND operation='call.interests'
                AND resource_id=ANY(targets) AND state IN ('pending','sending');
        END $$;
    """)
    op.execute("""
        CREATE FUNCTION on_call_consent_revoked() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM invalidate_member_search(NEW.id);
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER call_consent_revoked AFTER UPDATE OF call_agree ON seniors
        FOR EACH ROW WHEN (OLD.call_agree AND NOT NEW.call_agree)
        EXECUTE FUNCTION on_call_consent_revoked()
    """)


def downgrade():
    op.execute("DROP TRIGGER call_consent_revoked ON seniors")
    op.execute("DROP FUNCTION on_call_consent_revoked()")
    op.execute("DROP FUNCTION invalidate_member_search(uuid)")
    op.drop_table("refresh_sessions")
    op.drop_column("idempotency_records", "resource_id")
    op.drop_column("users", "withdrawn_at")
    op.drop_column("users", "kakao_user_id")
