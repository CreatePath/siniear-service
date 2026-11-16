from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import CancellationNotice, Meeting, Registration, RegistrationAction
from app.modules.auth.dependencies import Principal
from app.modules.meetings import cancellation, registration_service
from scripts.seed_dev import ids
from tests.integration.test_groups_meetings import auth, create_group, create_meeting, meeting_data


def signup(api, meeting, name="member", key="request-1"):
    return api.post(
        f"/api/meetings/{meeting['id']}/registrations",
        headers={**auth(name), "Idempotency-Key": key},
    )


def cancel(api, meeting, registration, version, name="member"):
    return api.delete(
        f"/api/meetings/{meeting['id']}/registrations/{registration['id']}",
        headers={**auth(name), "If-Match": f'"{version}"'},
    )


def test_idempotency_cancel_reregister(api, db_engine):
    meeting = create_meeting(api)
    first = signup(api, meeting)
    assert first.status_code == 201, first.text
    registration = first.json()
    assert signup(api, meeting).json() == registration
    duplicate = signup(api, meeting, key="request-2")
    assert duplicate.status_code == 200
    assert duplicate.json() == registration
    assert cancel(api, meeting, registration, 1, "other").status_code == 403
    assert cancel(api, meeting, registration, 1).status_code == 204
    assert cancel(api, meeting, registration, 1).status_code == 409
    assert cancel(api, meeting, registration, 2).status_code == 204
    # Lost response retries replay the original result even after cancellation.
    assert signup(api, meeting).json() == registration
    again = signup(api, meeting, key="request-3")
    assert again.status_code == 200
    assert again.json()["id"] == registration["id"]
    assert again.json()["version"] == 3
    assert again.json()["created_at"] == registration["created_at"]
    another_meeting = create_meeting(api)
    assert signup(api, another_meeting).status_code == 409
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(RegistrationAction)) == 3


def test_capacity_and_manager_cancel(api):
    meeting = create_meeting(api, capacity=1)
    registration = signup(api, meeting).json()
    assert signup(api, meeting, "other").json()["error"]["code"] == "MEETING_FULL"
    assert api.patch(f"/api/meetings/{meeting['id']}", json={"capacity": 2}).status_code == 200
    assert signup(api, meeting, "other").status_code == 201
    assert api.patch(f"/api/meetings/{meeting['id']}", json={"capacity": 1}).status_code == 409
    assert cancel(api, meeting, registration, 1, "owner").status_code == 204


def test_cancel_after_deadline_before_start(api, db_engine):
    meeting = create_meeting(api)
    registration = signup(api, meeting).json()
    with Session(db_engine) as session, session.begin():
        session.get(Meeting, UUID(meeting["id"])).registration_closes_at = datetime.now(
            UTC
        ) - timedelta(minutes=1)
    assert signup(api, meeting, "other").status_code == 409
    assert cancel(api, meeting, registration, 1).status_code == 204


def test_group_closure_preserves_completed_history(api, db_engine):
    group = create_group(api)
    data = meeting_data()
    del data["region_code"]
    meeting = api.post(f"/api/groups/{group['id']}/meetings", json=data).json()
    past = api.post(f"/api/groups/{group['id']}/meetings", json=data).json()
    signup(api, meeting)
    signup(api, past, key="past")
    with Session(db_engine) as session, session.begin():
        row = session.get(Meeting, UUID(past["id"]))
        row.starts_at = datetime.now(UTC) - timedelta(days=2)
        row.ends_at = datetime.now(UTC) - timedelta(days=1)
        row.registration_closes_at = row.starts_at
    path = f"/api/groups/{group['id']}"
    assert api.patch(path, json={"status": "closed"}, headers=auth("other")).status_code == 403
    assert api.patch(path, json={"status": "closed"}).status_code == 200
    assert api.patch(path, json={"status": "closed"}).status_code == 200
    assert api.post(path + "/meetings", json=data).status_code == 409
    assert signup(api, meeting, "other").status_code == 409
    with Session(db_engine) as session:
        assert session.get(Meeting, UUID(past["id"])).status == "completed"
        assert (
            session.scalar(
                select(Registration.status).where(Registration.meeting_id == UUID(past["id"]))
            )
            == "confirmed"
        )
        assert (
            session.scalar(
                select(Registration.status).where(Registration.meeting_id == UUID(meeting["id"]))
            )
            == "canceled"
        )
        assert session.scalar(select(func.count()).select_from(CancellationNotice)) == 2
        assert session.scalar(select(func.count()).select_from(RegistrationAction)) == 3


def test_cancellation_is_atomic(api, db_engine, monkeypatch):
    meeting = create_meeting(api)
    signup(api, meeting)
    original = cancellation.record_action

    def fail_after_action(*args):
        original(*args)
        raise RuntimeError("simulated storage failure")

    monkeypatch.setattr(cancellation, "record_action", fail_after_action)
    with pytest.raises(RuntimeError):
        api.patch(
            f"/api/meetings/{meeting['id']}",
            json={"status": "canceled", "cancel_reason": "가상 사유"},
        )
    with Session(db_engine) as session:
        assert session.get(Meeting, UUID(meeting["id"])).status == "recruiting"
        assert session.scalar(select(Registration.status)) == "confirmed"
        assert session.scalar(select(func.count()).select_from(RegistrationAction)) == 1
        assert session.scalar(select(func.count()).select_from(CancellationNotice)) == 0


def test_last_seat_and_same_key_concurrency(api, db_engine):
    meeting = create_meeting(api, capacity=1)
    barrier = Barrier(2)
    key = "race"

    def compete(name):
        with Session(db_engine) as session:
            barrier.wait(timeout=5)
            try:
                return registration_service.register(
                    session, Principal(*ids(name)), UUID(meeting["id"]), key
                )
            except DomainError as exc:
                return exc.status, exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, ["member", "other"]))
    assert sorted(status for status, _ in results) == [201, 409]
    meeting = create_meeting(api)
    key = "same-key-race"
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, ["member", "member"]))
    assert [status for status, _ in results] == [201, 201]
    assert results[0][1] == results[1][1]
    with Session(db_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Registration)
                .where(Registration.meeting_id == UUID(meeting["id"]))
            )
            == 1
        )
