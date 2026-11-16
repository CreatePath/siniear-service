import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Meeting, Registration, Senior
from app.workers.meeting_status import refresh_statuses
from scripts.seed_dev import ids
from tests.integration.test_groups_meetings import auth, create_group, create_meeting, meeting_data
from tests.integration.test_registrations import cancel, signup


def test_search_pagination_and_filter_binding(api):
    groups = [create_group(api) for _ in range(3)]
    first = api.get("/api/groups", params={"limit": 2}).json()
    second = api.get("/api/groups", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert {row["id"] for row in first["items"] + second["items"]} == {row["id"] for row in groups}
    assert second["next_cursor"] is None
    assert api.get("/api/groups", params={"keyword": "%"}).json()["items"] == []
    assert (
        api.get(
            "/api/groups", params={"region_code": "other", "cursor": first["next_cursor"]}
        ).status_code
        == 422
    )
    for cursor in ["bad!", base64.b64encode(b"[]").decode(), base64.b64encode(b"null").decode()]:
        assert api.get("/api/groups", params={"cursor": cursor}).status_code == 422
    data = meeting_data()
    meetings = [api.post("/api/meetings", json=data).json() for _ in range(3)]
    page = api.get("/api/meetings", params={"limit": 2, "from": data["starts_at"]}).json()
    following = api.get(
        "/api/meetings",
        params={"limit": 2, "from": data["starts_at"], "cursor": page["next_cursor"]},
    ).json()
    assert len({row["id"] for row in page["items"] + following["items"]}) == len(meetings)
    assert api.get("/api/meetings", params={"to": data["starts_at"]}).json()["items"] == []
    assert api.get("/api/meetings", params={"from": "2030-01-01T12:00:00"}).status_code == 422
    assert (
        api.get(
            "/api/meetings", params={"from": data["ends_at"], "to": data["starts_at"]}
        ).status_code
        == 422
    )


def test_recommendations_and_private_lists(api, db_engine):
    group = create_group(api)
    data = meeting_data()
    del data["region_code"]
    grouped = api.post(f"/api/groups/{group['id']}/meetings", json=data).json()
    independent = create_meeting(api)
    full = create_meeting(api, capacity=1)
    signup(api, full, "other", "fill")
    create_meeting(api, region_code="other")
    path = f"/api/seniors/{ids('member')[1]}/meeting-recommendations"
    assert api.get(path).status_code == 403
    response = api.get(path, headers=auth("member"))
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["items"]] == [grouped["id"], independent["id"]]
    registration = signup(api, independent).json()
    assert [row["id"] for row in api.get(path, headers=auth("member")).json()["items"]] == [
        grouped["id"]
    ]
    my_path = f"/api/seniors/{ids('member')[1]}/registrations"
    assert api.get(my_path).status_code == 403
    listed = api.get(my_path, headers=auth("member")).json()["items"][0]
    assert listed["id"] == registration["id"]
    assert listed["meeting"]["title"] == independent["title"]
    participants = f"/api/meetings/{independent['id']}/registrations"
    assert api.get(participants, headers=auth("member")).status_code == 403
    assert "phone_number" not in str(api.get(participants).json())
    with Session(db_engine) as session, session.begin():
        session.get(Senior, ids("member")[1]).interests = []
    assert api.get(path, headers=auth("member")).status_code == 200


def test_updates_and_effective_status(api, db_engine):
    meeting = create_meeting(api)
    path = f"/api/meetings/{meeting['id']}"
    for body in [
        {},
        {"title": None},
        {"owner_id": str(ids("member")[1])},
        {"status": "canceled"},
        {"cancel_reason": "이유"},
        {"status": "completed"},
    ]:
        assert api.patch(path, json=body).status_code == 422
    assert api.patch(path, json={"title": "다른 제목"}, headers=auth("member")).status_code == 403
    assert api.patch(path, json={"starts_at": meeting["ends_at"]}).status_code == 422
    assert api.get(path).json()["starts_at"] == meeting["starts_at"]
    assert api.patch(path, json={"status": "closed"}).status_code == 200
    assert signup(api, meeting).status_code == 409
    assert api.patch(path, json={"status": "recruiting"}).status_code == 200
    registration = signup(api, meeting).json()
    with Session(db_engine) as session, session.begin():
        row = session.get(Meeting, UUID(meeting["id"]))
        row.starts_at = datetime.now(UTC) - timedelta(minutes=1)
        row.registration_closes_at = row.starts_at
    assert api.get(path).json()["status"] == "closed"
    assert cancel(api, meeting, registration, 1).json()["error"]["code"] == "CANCELLATION_CLOSED"
    with Session(db_engine) as session:
        assert refresh_statuses(session) == {"completed": 0, "closed": 1}
        assert refresh_statuses(session) == {"completed": 0, "closed": 0}


def test_repeat_meeting_cancel_and_group_region_snapshot(api, db_engine):
    group = create_group(api)
    data = meeting_data()
    del data["region_code"]
    meeting = api.post(f"/api/groups/{group['id']}/meetings", json=data).json()
    assert api.patch(f"/api/groups/{group['id']}", json={"region_code": "other"}).status_code == 200
    path = f"/api/meetings/{meeting['id']}"
    assert api.get(path).json()["region_code"] == "11110"
    signup(api, meeting)
    body = {"status": "canceled", "cancel_reason": "우천 취소"}
    assert api.patch(path, json=body).status_code == 200
    assert api.patch(path, json=body).status_code == 200
    assert api.get(path).json()["participant_count"] == 0
    assert api.patch(path, json={"status": "recruiting"}).status_code == 409
    from app.db.models import CancellationNotice, RegistrationAction

    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(CancellationNotice)) == 2
        assert session.scalar(select(func.count()).select_from(RegistrationAction)) == 2


def test_migration_schema_and_database_constraints(api, db_engine):
    meeting = create_meeting(api)
    with db_engine.begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.check(config)
    with pytest.raises(IntegrityError), db_engine.begin() as connection:
        connection.execute(
            text("UPDATE meetings SET capacity=0 WHERE id=:id"), {"id": meeting["id"]}
        )
    with pytest.raises(IntegrityError), Session(db_engine) as session, session.begin():
        session.add(
            Registration(
                meeting_id=UUID(meeting["id"]),
                senior_id=ids("member")[1],
                status="confirmed",
                call_id=UUID(meeting["id"]),
            )
        )
    # Downgrade/upgrade is performed only inside the fixture's throwaway schema.
    with db_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
        command.upgrade(config, "head")


def test_corrupt_capacity_is_not_hidden(api, db_engine):
    meeting = create_meeting(api, capacity=2)
    assert signup(api, meeting).status_code == 201
    assert signup(api, meeting, "other").status_code == 201
    with Session(db_engine) as session, session.begin():
        session.get(Meeting, UUID(meeting["id"])).capacity = 1
    response = api.get(f"/api/meetings/{meeting['id']}")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "DATA_INTEGRITY_ERROR"
