from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.call import (
    AlertDelivery,
    Call,
    CallEpisode,
    CallSchedule,
    CareContact,
    EmergencyAlert,
)
from app.db.models.call_runtime import OutboxMessage
from app.modules.calls.scheduler import tick
from app.modules.emergency.service import consider_alert, queue_next
from app.workers.outbox import deliver_one
from scripts.seed_dev import ids
from tests.integration.conftest import auth


def make_schedule(api, name="owner"):
    senior_id = ids(name)[1]
    response = api.post(
        f"/api/seniors/{senior_id}/call-schedules",
        headers=auth(name),
        json={
            "days_of_week": ["MON", "WED", "MON"],
            "local_time": "10:00",
            "timezone": "Asia/Seoul",
            "enabled": True,
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def due(db_engine, schedule_id, at):
    with Session(db_engine) as session, session.begin():
        session.get(CallSchedule, schedule_id).next_call_at = at


def test_schedule_permissions_validation_and_delete(api, db_engine):
    schedule = make_schedule(api)
    path = f"/api/seniors/{ids('owner')[1]}/call-schedules/{schedule}"
    assert api.patch(path, headers=auth("other"), json={"enabled": False}).status_code == 403
    assert api.patch(path, json={"local_time": "24:00"}).status_code == 422
    assert api.patch(path, json={"timezone": "UTC"}).status_code == 422
    assert api.patch(path, json={}).status_code == 422
    assert api.patch(path, json={"enabled": False}).json()["next_call_at"] is None
    assert api.delete(path).status_code == 204
    assert api.get(f"/api/seniors/{ids('owner')[1]}/call-schedules").json()["items"] == []
    response = api.post(
        f"/api/seniors/{ids('no_consent')[1]}/call-schedules",
        headers=auth("no_consent"),
        json={
            "days_of_week": ["MON"],
            "local_time": "10:00",
            "timezone": "Asia/Seoul",
            "enabled": True,
        },
    )
    assert response.status_code == 403


def test_scheduler_concurrent_once_and_retry_spacing(api, db_engine):
    schedule = make_schedule(api)
    at = datetime.now(UTC)
    due(db_engine, schedule, at)
    with ThreadPoolExecutor(2) as pool:
        counts = list(pool.map(lambda _: tick(db_engine, at), range(2)))
    assert sum(counts) == 1
    with Session(db_engine) as session, session.begin():
        call = session.scalar(select(Call))
        first_id = call.id
        call.status, call.ended_at = "no_answer", at
    assert tick(db_engine, at + timedelta(seconds=179)) == 0
    assert tick(db_engine, at + timedelta(seconds=180)) == 1
    with Session(db_engine) as session:
        calls = list(session.scalars(select(Call).order_by(Call.attempt_no)))
        assert (
            len(calls) == 2
            and calls[1].id != first_id
            and calls[1].episode_id == calls[0].episode_id
        )
        assert session.scalar(select(func.count()).select_from(CallEpisode)) == 1
    path = f"/api/seniors/{ids('owner')[1]}/calls"
    assert len(api.get(path).json()["items"]) == 2
    assert api.get(path, headers=auth("other")).status_code == 403
    detail = api.get(path + f"/{first_id}").json()
    assert detail["summary"] is None and "embedding" not in detail and "transcript" not in detail


@pytest.mark.parametrize("status", ["busy", "failed", "canceled", "completed"])
def test_technical_results_do_not_retry_or_alert(api, db_engine, status):
    schedule = make_schedule(api)
    at = datetime.now(UTC)
    due(db_engine, schedule, at)
    tick(db_engine, at)
    with Session(db_engine) as session, session.begin():
        call = session.scalar(select(Call))
        call.status = status
        call.ended_at = at
    assert tick(db_engine, at + timedelta(minutes=4)) == 0
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(EmergencyAlert)) == 0


def test_outbox_replays_same_id_key_body_after_timeout(api, db_engine):
    schedule = make_schedule(api)
    at = datetime.now(UTC)
    due(db_engine, schedule, at)
    tick(db_engine, at)
    sent = []

    def send(*args):
        sent.append(args)
        if len(sent) == 1:
            raise TimeoutError

    assert deliver_one(db_engine, "C", send, at)
    assert deliver_one(db_engine, "C", send, at + timedelta(minutes=1))
    assert sent[0] == sent[1]
    with Session(db_engine) as session:
        assert session.scalar(select(OutboxMessage)).state == "delivered"


def test_emergency_three_contacts_registration_order_and_once(api, db_engine):
    schedule = make_schedule(api)
    at = datetime.now(UTC)
    due(db_engine, schedule, at)
    tick(db_engine, at)
    with Session(db_engine) as session, session.begin():
        from app.db.models import Senior

        senior = session.get(Senior, ids("owner")[1])
        first = session.scalar(select(Call))
        first.status = "no_answer"
        first.ended_at = at
        for attempt in [2, 3]:
            session.add(
                Call(
                    episode_id=first.episode_id, attempt_no=attempt, status="no_answer", ended_at=at
                )
            )
        contacts = []
        for n in range(4):
            c = CareContact(
                id=uuid4(),
                senior_id=senior.id,
                name=f"가상연락처{n}",
                phone_number=f"+82100000010{n}",
                created_at=at + timedelta(seconds=n),
            )
            session.add(c)
            contacts.append(c.id)
        session.flush()
        third = session.scalar(select(Call).where(Call.attempt_no == 3))
        consider_alert(session, senior, third, at)
        consider_alert(session, senior, third, at)
        session.flush()
        alert = session.scalar(select(EmergencyAlert))
        assert session.scalar(select(func.count()).select_from(EmergencyAlert)) == 1
        for n in range(3):
            delivery = session.scalar(select(AlertDelivery).where(AlertDelivery.status == "queued"))
            assert delivery.contact_id == contacts[n]
            delivery.status = "no_answer"
            session.flush()
            queue_next(session, senior, alert, at)
        assert alert.status == "failed" and alert.failure_reason == "all_contacts_failed"
        assert session.scalar(select(func.count()).select_from(AlertDelivery)) == 3


def test_internal_app_token_and_unproven_event_rejected(api, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("INTERNAL_INBOUND_TOKEN", "test-service-secret")
    get_settings.cache_clear()
    path = f"/api/internal/calls/{uuid4()}/events"
    payload = {
        "event_id": "event1",
        "occurred_at": datetime.now(UTC).isoformat(),
        "status": "no_answer",
    }
    assert api.post(path, json=payload).status_code == 401
    assert (
        api.post(
            path, json=payload, headers={"Authorization": "Bearer test-service-secret"}
        ).status_code
        == 409
    )
