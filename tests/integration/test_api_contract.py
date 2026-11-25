from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import IdentityVerification
from scripts.seed_dev import ids
from tests.integration.test_groups_meetings import create_meeting
from tests.integration.test_registrations import signup


def test_auth_disabled_and_later_failed_verification(api, db_engine, monkeypatch):
    with Session(db_engine) as session, session.begin():
        session.add(IdentityVerification(user_id=ids("owner")[0], status="failed"))
    assert api.get("/api/groups").status_code == 200
    monkeypatch.setenv("DEV_AUTH_ENABLED", "false")
    get_settings.cache_clear()
    assert api.get("/api/groups").status_code == 401
    assert api.get("/api/internal/calls").status_code == 404
    with Session(db_engine) as session:
        assert (
            session.scalar(
                select(IdentityVerification.id).where(
                    IdentityVerification.user_id == ids("owner")[0],
                    IdentityVerification.status == "verified",
                )
            )
            is not None
        )


def test_required_headers_body_and_openapi(api):
    meeting = create_meeting(api)
    path = f"/api/meetings/{meeting['id']}/registrations"
    assert api.post(path).status_code == 422
    assert (
        api.post(
            path, headers={"Idempotency-Key": "body"}, json={"senior_id": str(ids("other")[1])}
        ).status_code
        == 422
    )
    registration = signup(api, meeting).json()
    assert api.delete(path + f"/{registration['id']}").status_code == 422
    schema = api.get("/api/openapi.json").json()
    post = schema["paths"]["/api/meetings/{meeting_id}/registrations"]["post"]
    assert {"200", "201", "401", "403", "409", "422"} <= post["responses"].keys()
    assert post["responses"]["422"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ErrorResponse"
    )
    assert post["security"] == [{"HTTPBearer": []}]
    assert "requestBody" not in post


def test_retired_routes_are_absent(api):
    paths = api.get("/api/openapi.json").json()["paths"]
    retired = {"care-contacts", "call-schedules", "calls", "alerts", "internal"}
    assert all(retired.isdisjoint(path.split("/")) for path in paths)
    senior = ids("member")[1]
    for method, path in (
        ("GET", f"/api/seniors/{senior}/care-contacts"),
        ("POST", f"/api/seniors/{senior}/care-contacts"),
        ("PATCH", f"/api/seniors/{senior}/care-contacts/{senior}"),
        ("DELETE", f"/api/seniors/{senior}/care-contacts/{senior}"),
        ("POST", f"/api/seniors/{senior}/call-schedules"),
        ("GET", f"/api/seniors/{senior}/alerts"),
        ("POST", f"/api/internal/calls/{senior}/registrations"),
    ):
        assert api.request(method, path).status_code == 404
