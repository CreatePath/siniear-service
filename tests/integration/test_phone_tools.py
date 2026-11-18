from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.call import Call, TranscriptTurn
from app.modules.calls.scheduler import tick
from scripts.seed_dev import ids
from tests.integration.test_calls import due, make_schedule


def active_call(api, db_engine, monkeypatch):
    monkeypatch.setenv("INTERNAL_INBOUND_TOKEN", "test-T-to-C")
    get_settings.cache_clear()
    schedule = make_schedule(api)
    at = datetime.now(UTC)
    due(db_engine, schedule, at)
    tick(db_engine, at)
    with Session(db_engine) as session, session.begin():
        call = session.scalar(select(Call))
        call.status = "in_progress"
        call.answered_at = at
        return call.id


def meeting(api):
    from datetime import timedelta

    at = datetime.now(UTC) + timedelta(days=1)
    response = api.post(
        "/api/meetings",
        json={
            "title": "가상 산책",
            "description": "",
            "region_code": "41110",
            "starts_at": at.isoformat(),
            "ends_at": (at + timedelta(hours=1)).isoformat(),
            "location": "가상 공원",
            "capacity": 3,
            "registration_closes_at": at.isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def consent(db_engine, call_id, meeting_id, action, registration=None, text="네"):
    announcement, confirmation = str(uuid4()), str(uuid4())
    context = {"action": action, "meeting_id": meeting_id}
    if registration:
        context.update(registration_id=registration["id"], expected_version=registration["version"])
    with Session(db_engine) as session, session.begin():
        session.add(
            TranscriptTurn(
                call_id=call_id,
                turn_id=announcement,
                speaker="assistant",
                text="가상 일정 안내",
                offset_ms=100,
                action_context=context,
            )
        )
        session.add(
            TranscriptTurn(
                call_id=call_id,
                turn_id=confirmation,
                speaker="user",
                text=text,
                offset_ms=200,
                action_context={**context, "announcement_turn_id": announcement},
            )
        )
    return confirmation


def test_phone_registration_cancel_and_replay_after_hangup(api, db_engine, monkeypatch):
    call_id = active_call(api, db_engine, monkeypatch)
    mid = meeting(api)
    turn = consent(db_engine, call_id, mid, "register")
    path = f"/api/internal/calls/{call_id}/registrations"
    headers = {"Authorization": "Bearer test-T-to-C", "Idempotency-Key": "phone-reg"}
    payload = {"meeting_id": mid, "confirmation_turn_id": turn}
    response = api.post(path, json=payload, headers=headers)
    assert response.status_code == 201, response.text
    registration = response.json()
    assert registration["source"] == "phone"
    assert (
        api.post(
            path, json=payload, headers={**headers, "Idempotency-Key": "reused-evidence"}
        ).status_code
        == 409
    )
    cancel_turn = consent(db_engine, call_id, mid, "cancel", registration)
    cancel_path = path + f"/{registration['id']}/cancel"
    canceled = api.post(
        cancel_path,
        json={"confirmation_turn_id": cancel_turn, "expected_version": 1},
        headers={**headers, "Idempotency-Key": "phone-cancel"},
    )
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "canceled" and canceled.json()["version"] == 2
    with Session(db_engine) as session, session.begin():
        session.get(Call, call_id).status = "completed"
    assert api.post(path, json=payload, headers=headers).json() == registration


def test_ambiguous_confirmation_and_scope_are_rejected(api, db_engine, monkeypatch):
    call_id = active_call(api, db_engine, monkeypatch)
    mid = meeting(api)
    turn = consent(db_engine, call_id, mid, "register", text="잘 모르겠어요")
    path = f"/api/internal/calls/{call_id}/registrations"
    headers = {"Authorization": "Bearer test-T-to-C", "Idempotency-Key": "phone-reg"}
    payload = {"meeting_id": mid, "confirmation_turn_id": turn}
    assert api.post(path, json=payload, headers=headers).status_code == 409
    monkeypatch.setenv("INTERNAL_SCOPES", "calls:events")
    get_settings.cache_clear()
    assert api.post(path, json=payload, headers=headers).status_code == 403


def test_interest_merge_requires_current_consent(api, db_engine, monkeypatch):
    call_id = active_call(api, db_engine, monkeypatch)
    headers = {"Authorization": "Bearer test-T-to-C", "Idempotency-Key": "interests"}
    path = f"/api/internal/calls/{call_id}/interests"
    first = api.post(path, headers=headers, json={"interests": ["독서", "독서"]})
    assert first.status_code == 200
    assert first.json()["interests"].count("독서") == 1
    assert api.post(path, headers=headers, json={"interests": ["다른 관심사"]}).status_code == 409
    from app.db.models import Senior

    with Session(db_engine) as session, session.begin():
        session.get(Senior, ids("owner")[1]).call_agree = False
    assert api.post(path, headers=headers, json={"interests": ["독서", "독서"]}).status_code == 403


def test_noop_confirmation_cannot_reregister_after_app_cancel(api, db_engine, monkeypatch):
    call_id = active_call(api, db_engine, monkeypatch)
    mid = meeting(api)
    app_registration = api.post(
        f"/api/meetings/{mid}/registrations", headers={"Idempotency-Key": "app-registration"}
    ).json()
    turn = consent(db_engine, call_id, mid, "register")
    path = f"/api/internal/calls/{call_id}/registrations"
    headers = {"Authorization": "Bearer test-T-to-C", "Idempotency-Key": "phone-noop"}
    payload = {"meeting_id": mid, "confirmation_turn_id": turn}
    assert api.post(path, json=payload, headers=headers).status_code == 200
    assert (
        api.delete(
            f"/api/meetings/{mid}/registrations/{app_registration['id']}",
            headers={"If-Match": '"1"'},
        ).status_code
        == 204
    )
    assert (
        api.post(
            path, json=payload, headers={**headers, "Idempotency-Key": "reuse-old-noop"}
        ).status_code
        == 409
    )
