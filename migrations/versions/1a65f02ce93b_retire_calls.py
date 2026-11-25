"""비상연락처와 안부전화 전용 데이터 제거."""

from alembic import op

revision = "1a65f02ce93b"
down_revision = "f830ad2d4c19"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP TRIGGER call_consent_revoked ON seniors")
    op.execute("DROP FUNCTION on_call_consent_revoked()")
    op.execute("DROP FUNCTION invalidate_member_search(uuid)")

    # PostgreSQL drops the local foreign keys, checks and indexes of these columns.
    op.drop_column("meeting_registrations", "call_id")
    op.drop_column("registration_actions", "call_id")
    op.drop_column("registration_actions", "confirmation_turn_id")
    op.drop_column("seniors", "phone_number")
    op.drop_column("seniors", "call_agree")

    op.execute("""
        DELETE FROM idempotency_records
        WHERE (owner_service = 'T' AND operation IN ('call.start', 'emergency.start'))
           OR (owner_service = 'C' AND operation IN
                   ('phone.register', 'phone.cancel', 'phone.confirmation'))
           OR (owner_service = 'C' AND subject_id = 'T' AND operation = 'interests')
    """)
    op.execute("""
        UPDATE idempotency_records
        SET response_body = response_body - 'source' - 'call_id'
        WHERE owner_service = 'C' AND operation = 'meeting.register'
          AND (response_body ? 'source' OR response_body ? 'call_id')
    """)
    op.execute("DELETE FROM cancellation_notices WHERE kind = 'organizer_phone_guidance'")
    op.drop_constraint(op.f("ck_cancellation_notices_kind"), "cancellation_notices", type_="check")
    op.create_check_constraint("kind", "cancellation_notices", "kind = 'meeting_canceled'")

    for table in (
        "call_executions",
        "alert_deliveries",
        "emergency_alerts",
        "care_contacts",
        "transcript_turns",
        "call_processing_jobs",
        "calls",
        "call_episodes",
        "call_schedules",
        "outbox_messages",
        "inbox_events",
    ):
        op.drop_table(table)


def downgrade():
    raise RuntimeError("삭제한 통화·연락처 데이터를 복구하려면 전환 전 백업을 복원하세요.")
