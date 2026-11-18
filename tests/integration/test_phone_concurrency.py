from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.modules.meetings import phone_service
from app.modules.meetings.internal_router import PhoneCancel
from tests.integration.test_phone_tools import active_call, consent, meeting


def test_phone_cancel_rechecks_version_after_waiting_for_app(api, db_engine, monkeypatch):
    call_id = active_call(api, db_engine, monkeypatch)
    mid = meeting(api)
    registration = api.post(
        f"/api/meetings/{mid}/registrations", headers={"Idempotency-Key": "app-registration"}
    ).json()
    turn = consent(db_engine, call_id, mid, "cancel", registration)
    checked, proceed = Event(), Event()
    original = phone_service.validate_confirmation

    def pause(*args, **kwargs):
        original(*args, **kwargs)
        checked.set()
        assert proceed.wait(10)

    monkeypatch.setattr(phone_service, "validate_confirmation", pause)

    def phone_cancel():
        with Session(db_engine) as session:
            return phone_service.cancel(
                session,
                call_id,
                UUID(registration["id"]),
                PhoneCancel(confirmation_turn_id=turn, expected_version=1),
                "phone-race",
            )

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(phone_cancel)
        try:
            assert checked.wait(10)
            result = api.delete(
                f"/api/meetings/{mid}/registrations/{registration['id']}",
                headers={"If-Match": '"1"'},
            )
            assert result.status_code == 204
        finally:
            proceed.set()
        with pytest.raises(DomainError) as error:
            future.result(timeout=10)
        assert error.value.code == "REGISTRATION_CHANGED"
