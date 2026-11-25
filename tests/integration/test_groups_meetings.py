from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Senior, User
from scripts.seed_dev import ids, seed


def auth(name):
    return {"Authorization": f"Bearer dev:{ids(name)[0]}"}


def meeting_data(**changes):
    start = datetime.now(UTC) + timedelta(days=2)
    return {
        "title": "가상 산책 일정",
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=1)).isoformat(),
        "location": "가상공원",
        "capacity": 2,
        "registration_closes_at": (start - timedelta(hours=1)).isoformat(),
        "region_code": "11110",
        **changes,
    }


def create_group(api):
    response = api.post(
        "/api/groups",
        json={"name": "가상 산책 모임", "region_code": "11110", "interests": ["산책"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_meeting(api, **changes):
    response = api.post("/api/meetings", json=meeting_data(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def test_group_and_independent_meeting(api):
    group = create_group(api)
    assert group["owner_id"] == str(ids("owner")[1])
    data = meeting_data()
    del data["region_code"]
    assert (
        api.post(
            f"/api/groups/{group['id']}/meetings", json=data, headers=auth("member")
        ).status_code
        == 403
    )
    response = api.post(f"/api/groups/{group['id']}/meetings", json=data)
    assert response.status_code == 201, response.text
    assert response.json()["group_id"] == group["id"]
    independent = create_meeting(api)
    assert independent["group_id"] is None
    assert independent["remaining_capacity"] == 2
    assert api.get(f"/api/meetings/{independent['id']}", headers=auth("member")).status_code == 200


def test_authentication_and_owner_spoofing(api):
    data = {"name": "가상 모임", "region_code": "11110"}
    assert api.post("/api/groups", json=data, headers={"Authorization": ""}).status_code == 401
    assert api.post("/api/groups", json=data, headers=auth("unverified")).status_code == 201
    assert (
        api.post("/api/groups", json={**data, "owner_id": str(ids("other")[1])}).status_code == 422
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"capacity": 0},
        {"capacity": True},
        {"starts_at": "2030-01-01T10:00:00"},
        {"ends_at": "2000-01-01T10:00:00Z"},
        {"title": "   "},
        {"starts_at": "2000-01-01T10:00:00Z", "registration_closes_at": "1999-01-01T10:00:00Z"},
    ],
)
def test_meeting_validation(api, changes):
    response = api.post("/api/meetings", json=meeting_data(**changes))
    assert response.status_code == 422, response.text
    assert set(response.json()["error"]) == {"code", "message", "request_id"}


def test_seed_preserves_existing_data(db_engine):
    with Session(db_engine) as session, session.begin():
        session.get(Senior, ids("owner")[1]).interests = ["목공"]
    with Session(db_engine) as session, session.begin():
        seed(session)
        assert session.scalar(select(func.count()).select_from(User)) == 4
        assert session.get(Senior, ids("owner")[1]).interests == ["목공"]
