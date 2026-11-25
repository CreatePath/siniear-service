from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from scripts.seed_non_call_demo import seed


def test_upgrade_preserves_profiles_registrations_and_replays(schema_engine):
    with schema_engine.begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, "d824e81c48c2")
        with Session(connection) as session, session.begin():
            seed(session)
        profiles = text("SELECT id, user_id, name, interests FROM seniors ORDER BY id")
        registrations = text("""
            SELECT id, meeting_id, senior_id, status, version FROM meeting_registrations ORDER BY id
        """)
        actions = text("""
            SELECT registration_id, resulting_version, actor_senior_id, action, created_at
            FROM registration_actions ORDER BY registration_id
        """)
        queries = (profiles, registrations, actions)
        before = [connection.execute(query).all() for query in queries]
        assert all(before)
        command.upgrade(config, "f830ad2d4c19")

        # One historical registration was confirmed during a call.
        connection.exec_driver_sql("""
            INSERT INTO call_schedules (id, senior_id, days_of_week, local_time, enabled)
            SELECT gen_random_uuid(), senior_id, ARRAY['MON'], '09:00', false
            FROM meeting_registrations ORDER BY id LIMIT 1;
            INSERT INTO call_episodes (id, schedule_id, scheduled_at)
            SELECT gen_random_uuid(), id, now() FROM call_schedules;
            INSERT INTO calls (id, episode_id, attempt_no, status, transcript_status,
                               summary_status, indexing_status)
            SELECT gen_random_uuid(), id, 1, 'completed', 'complete', 'pending', 'pending'
            FROM call_episodes;
            INSERT INTO transcript_turns (call_id, turn_id, speaker, text, offset_ms)
            SELECT id, '1', 'user', 'test', 0 FROM calls;
            UPDATE meeting_registrations SET call_id=(SELECT id FROM calls)
            WHERE senior_id=(SELECT senior_id FROM call_schedules);
            UPDATE registration_actions a SET call_id=r.call_id, confirmation_turn_id='1'
            FROM meeting_registrations r WHERE a.registration_id=r.id AND r.call_id IS NOT NULL;
            INSERT INTO care_contacts (id, senior_id, name, phone_number, enabled)
            SELECT gen_random_uuid(), senior_id, 'test', '', false FROM call_schedules;
            INSERT INTO cancellation_notices
                (id, meeting_id, recipient_senior_id, kind, payload, state)
            SELECT gen_random_uuid(), meeting_id, senior_id, kind, '{}', 'pending'
            FROM meeting_registrations CROSS JOIN
              (VALUES ('meeting_canceled'), ('organizer_phone_guidance')) AS kinds(kind)
            WHERE call_id IS NOT NULL;
            INSERT INTO idempotency_records
                (id, owner_service, subject_id, operation, key, request_hash,
                 http_status, response_body)
            SELECT gen_random_uuid(), 'C', senior_id::text, op, 'original-key', 'digest', 200,
                   jsonb_build_object('id', id, 'version', version,
                                      'call_id', call_id, 'source', 'phone')
            FROM meeting_registrations CROSS JOIN
              (VALUES ('meeting.register'), ('phone.register')) AS ops(op)
            WHERE call_id IS NOT NULL;
        """)
        cached = connection.execute(
            text("""
            SELECT id, key, request_hash, http_status, response_body - 'source' - 'call_id'
            FROM idempotency_records WHERE operation='meeting.register'
        """)
        ).one()
        command.upgrade(config, "head")
        assert [connection.execute(query).all() for query in queries] == before
        assert (
            connection.execute(
                text("""
            SELECT id, key, request_hash, http_status, response_body FROM idempotency_records
        """)
            ).one()
            == cached
        )
        assert connection.scalars(text("SELECT kind FROM cancellation_notices")).all() == [
            "meeting_canceled"
        ]
        assert connection.execute(
            text("SELECT DISTINCT version, avatar_key, activity_goals FROM seniors")
        ).one() == (1, "default", [])
        assert connection.scalar(text("SELECT count(*) FROM cards")) == 0
        assert {"calls", "care_contacts", "emergency_alerts"}.isdisjoint(
            inspect(connection).get_table_names()
        )
        command.check(config)
