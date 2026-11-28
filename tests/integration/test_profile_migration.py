import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
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
        migrated_profiles = text("SELECT id,user_id,nickname,interests FROM seniors ORDER BY id")
        assert connection.execute(text("SELECT count(*), count(category) FROM meetings")).one() == (
            4,
            0,
        )
        assert connection.execute(migrated_profiles).all() == before[0]
        assert [connection.execute(query).all() for query in queries[1:]] == before[1:]
        assert connection.scalar(text("SELECT count(*) FROM seniors WHERE name IS NOT NULL")) == 0
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
        assert (
            connection.scalar(text("SELECT count(*) FROM cards WHERE membership_id IS NULL")) == 0
        )
        assert (
            connection.scalar(text("SELECT count(*) FROM cards WHERE membership_id IS NOT NULL"))
            == 2
        )
        assert {"calls", "care_contacts", "emergency_alerts"}.isdisjoint(
            inspect(connection).get_table_names()
        )
        command.check(config)


def test_activity_backfill_preserves_selected_title_and_counts_only_period_activity(schema_engine):
    with schema_engine.begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, "d824e81c48c2")
        with Session(connection) as session, session.begin():
            seed(session)
        command.upgrade(config, "aa2611000004")
        member = connection.execute(
            text("""
            SELECT m.id, m.group_id, m.senior_id, c.id AS card_id FROM group_memberships m
            JOIN cards c ON c.membership_id=m.id ORDER BY m.id LIMIT 1
        """)
        ).one()
        params = dict(member._mapping)
        # The demo may contain posts timestamped later than the test transaction start.
        connection.execute(
            text("""
            UPDATE posts SET created_at=now()-interval '1 day'
            WHERE group_id=:group_id AND author_id=:senior_id
        """),
            params,
        )
        connection.execute(
            text("""
            UPDATE group_memberships SET joined_at=now() WHERE id=:id
        """),
            params,
        )
        connection.execute(
            text("""
            INSERT INTO posts (id, group_id, author_id, title, content, created_at, deleted_at)
            SELECT gen_random_uuid(), :group_id, :senior_id, 'fixture', 'fixture',
                   now() + n * interval '1 second', now() + interval '1 hour'
            FROM generate_series(-10,9) n
        """),
            params,
        )
        previous = connection.execute(
            text("""
            INSERT INTO membership_titles(id,membership_id,label,evidence_ref)
            VALUES(gen_random_uuid(),:id,'이야기꾼','old') RETURNING id
        """),
            params,
        ).scalar_one()
        params["selected"] = previous
        connection.execute(
            text("""
            UPDATE cards SET selected_title_id=:selected WHERE id=:card_id
        """),
            params,
        )
        connection.execute(
            text("""
            INSERT INTO card_exchanges(id,card_low_id,card_high_id)
            SELECT gen_random_uuid(), least(id,:card_id), greatest(id,:card_id)
            FROM cards WHERE id<>:card_id
        """),
            params,
        )
        params["meeting"] = connection.scalar(
            text("""
            INSERT INTO meetings(id,group_id,owner_id,region_code,title,description,starts_at,
                                 ends_at,location,capacity,registration_closes_at,status)
            VALUES(gen_random_uuid(),:group_id,:senior_id,'test','test','',now()+interval '1 day',
                   now()+interval '2 days','test',3,now(),'closed') RETURNING id
        """),
            params,
        )
        params["registration"] = connection.scalar(
            text("""
            INSERT INTO meeting_registrations(id,meeting_id,senior_id,status,version)
            VALUES(gen_random_uuid(),:meeting,:senior_id,'canceled',4) RETURNING id
        """),
            params,
        )
        connection.execute(
            text("""
            INSERT INTO registration_actions(registration_id,resulting_version,actor_senior_id,
                                             action,created_at)
            SELECT :registration,n,:senior_id,
                   CASE WHEN n IN (1,3) THEN 'register' ELSE 'cancel' END,
                   now()+n*interval '1 second' FROM generate_series(1,4) n
        """),
            params,
        )
        command.upgrade(config, "head")
        assert connection.execute(
            text("""
            SELECT post_count,exchange_count FROM group_memberships WHERE id=:id
        """),
            params,
        ).one() == (10, 1)
        awards = dict(
            connection.execute(
                text("""
            SELECT label,id FROM membership_titles WHERE membership_id=:id
        """),
                params,
            ).all()
        )
        assert set(awards) == {"신규 회원", "이야기꾼", "새로운 이웃", "새로운 얼굴"}
        assert awards["이야기꾼"] == previous
        assert (
            connection.scalar(text("SELECT selected_title_id FROM cards WHERE id=:card_id"), params)
            == previous
        )


def test_title_rule_fk_validates_existing_grants_and_preserves_selection(api, db_engine):
    from tests.integration.test_groups_meetings import create_group

    create_group(api)
    (period,) = api.get("/api/me/memberships").json()["items"]
    titles = f"/api/me/memberships/{period['id']}/titles"
    (grant,) = api.get(titles).json()["items"]
    card = "/api/cards/" + period["card_id"]
    assert (
        api.patch(
            card, headers={"If-Match": '"1"'}, json={"selected_title_id": grant["id"]}
        ).status_code
        == 200
    )

    with db_engine.begin() as conn:
        config = Config("alembic.ini")
        config.attributes["connection"] = conn
        command.downgrade(config, "aa2611000006")
        with conn.begin_nested() as previous_data:
            conn.execute(text("UPDATE membership_titles SET label='미등록'"))
            with pytest.raises(IntegrityError) as failed, conn.begin_nested():
                command.upgrade(config, "aa2611000007")
            assert failed.value.orig.sqlstate == "23503"
            assert conn.scalar(text("SELECT label FROM membership_titles")) == "미등록"
            previous_data.rollback()
        command.upgrade(config, "aa2611000007")
        for invalid in (
            "UPDATE membership_titles SET label='미등록'",
            "DELETE FROM activity_title_rules WHERE label='신규 회원'",
        ):
            with pytest.raises(IntegrityError) as failed, conn.begin_nested():
                conn.execute(text(invalid))
            assert failed.value.orig.sqlstate == "23503"
        conn.execute(
            text("UPDATE activity_title_rules SET label='새 회원' WHERE label='신규 회원'")
        )
        # Run the current card API against its schema after testing the historical FK.
        command.upgrade(config, "head")

    assert api.get(titles).json()["items"] == [{**grant, "label": "새 회원", "tier": "silver"}]
    selected = api.get(card).json()
    assert selected["top_encouragement_tags"] == []
    assert (selected["selected_title_id"], selected["selected_title_tier"]) == (
        grant["id"],
        "silver",
    )
