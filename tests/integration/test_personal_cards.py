from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.identity import Senior
from app.db.models.interview import Card, Interview, InterviewTurn
from app.db.models.registration import IdempotencyRecord
from scripts.seed_dev import ids
from tests.integration.conftest import auth
from tests.integration.test_interviews import ready


def confirmation(row):
    return {
        "version": row["version"],
        "profile_version": row["profile_version"],
        "card_version": None,
        "profile": {"intro": "직접 수정한 합성 소개"},
        "template_key": "classic",
        "visible_fields": ["intro"],
    }


def test_confirm_edit_and_withdraw(api, db_engine):
    row = ready(api)
    assert row["status"] == "ready" and row["draft"]["want_to_learn"]
    assert api.get("/api/me/cards").json()["items"] == []
    body = confirmation(row)
    url = f"/api/interviews/{row['id']}/confirm"
    preview_path = f"/api/interviews/{row['id']}/preview"
    preview = api.post(preview_path, json=body)
    assert preview.status_code == 200
    assert preview.json()["fields"] == {"intro": body["profile"]["intro"]}
    assert api.post(preview_path, headers=auth("other"), json=body).status_code == 404
    assert api.get("/api/me/cards").json()["items"] == []
    headers = {"Idempotency-Key": "confirm"}
    assert api.post(url, headers={**headers, **auth("other")}, json=body).status_code == 404
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: api.post(url, headers=headers, json=body), range(2)))
    assert all(r.status_code == 200 for r in results)
    first = results[0].json()
    assert first == results[1].json()
    card = first["card"]
    assert {key: card[key] for key in preview.json()} == preview.json()
    assert first["profile"]["experience"] is None
    assert card["fields"] == {"intro": body["profile"]["intro"]}
    assert api.get("/api/me/cards").json() == {"items": [card], "next_cursor": None}
    path = "/api/cards/" + card["id"]
    assert api.get(path, headers=auth("other")).status_code == 404
    assert api.get("/api/me/cards", headers=auth("other")).json()["items"] == []
    edit = {"visible_fields": []}
    version = {"If-Match": '"1"'}
    assert api.patch(path, headers={**auth("other"), **version}, json=edit).status_code == 404
    for invalid in (
        {},
        {"template_key": None},
        {"visible_fields": ["user_id"]},
        {"visible_fields": ["role"]},
        {"visible_fields": ["intro", "intro"]},
    ):
        assert api.patch(path, headers=version, json=invalid).status_code == 422
    updated = api.patch(path, headers=version, json=edit)
    assert updated.status_code == 200, updated.text
    assert updated.json()["fields"] == {}
    assert api.patch(path, headers=version, json=edit).status_code == 409
    assert api.post(url, headers=headers, json=body).json()["card"] == updated.json()
    assert api.post(url, headers={"Idempotency-Key": "other"}, json=body).status_code == 409
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(Card)) == 1
        assert all(
            not r.response_body
            for r in session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.operation.like("interview.%"))
            )
        )
    assert api.delete("/api/users/me").status_code == 204
    assert api.get(path).status_code == 401
    with Session(db_engine) as session:
        for table in (Card, Interview, InterviewTurn):
            assert session.scalar(select(func.count()).select_from(table)) == 0
        assert session.get(Senior, ids("owner")[1]).intro is None


def test_confirm_conflicts_do_not_apply_partial_changes(api):
    row = ready(api)
    url = f"/api/interviews/{row['id']}/confirm"
    headers = {"Idempotency-Key": "confirm"}
    body = confirmation(row)
    bad = {**body, "profile": {"photo_id": str(uuid4()), "intro": "합성"}}
    assert api.post(url, headers=headers, json=bad).status_code == 422
    assert api.post(url, headers=headers, json={**body, "card_version": 1}).status_code == 409
    assert api.get("/api/me/cards").json()["items"] == []
    path = f"/api/seniors/{ids('owner')[1]}"
    edited = api.patch(
        path, headers={"If-Match": '"1"'}, json={"intro": "먼저 저장한 합성 소개"}
    ).json()
    assert api.post(url, headers=headers, json=body).json()["error"]["code"] == "PROFILE_CHANGED"
    assert api.post(url, headers=headers, json={**body, "profile_version": 2}).status_code == 409
    assert api.get(path).json() == edited
    assert api.get(f"/api/interviews/{row['id']}").json()["status"] == "ready"
    assert api.get("/api/me/cards").json()["items"] == []


def test_reinterview_requires_latest_personal_card(api):
    first = ready(api)
    confirmed = api.post(
        f"/api/interviews/{first['id']}/confirm",
        headers={"Idempotency-Key": "one"},
        json=confirmation(first),
    ).json()
    card = confirmed["card"]
    second = ready(api, "second")
    body = {**confirmation(second), "card_version": card["version"]}
    path = f"/api/interviews/{second['id']}/confirm"
    assert (
        api.patch(
            "/api/cards/" + card["id"],
            headers={"If-Match": '"1"'},
            json={"template_key": "default"},
        ).status_code
        == 200
    )
    headers = {"Idempotency-Key": "two"}
    assert api.post(path, headers=headers, json=body).json()["error"]["code"] == "CARD_CHANGED"
    result = api.post(path, headers=headers, json={**body, "card_version": 2}).json()["card"]
    assert result["id"] == card["id"] and result["version"] == 3
