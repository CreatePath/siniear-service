from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Registration
from app.db.models.encouragement import EncouragementReport
from app.modules.community import encouragements
from app.modules.community.moderation import moderate
from scripts.seed_dev import ids
from tests.integration.conftest import auth, join
from tests.integration.test_exchange_book import offer, personal
from tests.integration.test_groups_meetings import create_group, create_meeting, meeting_data


def group_card(api, group, who):
    return next(
        c
        for c in api.get("/api/me/cards", headers=auth(who)).json()["items"]
        if c.get("group", {}).get("id") == group
    )


def exchange(api, mine, peer):
    response = api.post(
        "/api/exchanges",
        headers={"Idempotency-Key": str(uuid4())},
        json={"token": offer(api, "member", peer), "card_id": mine["id"]},
    )
    assert response.status_code == 201, response.text


def group_meeting(api, group):
    data = meeting_data()
    del data["region_code"]
    res = api.post(f"/api/groups/{group}/meetings", json=data)
    assert res.status_code == 201, res.text
    mid = res.json()["id"]
    for who in ["owner", "member"]:
        res = api.post(
            f"/api/meetings/{mid}/registrations", headers={**auth(who), "Idempotency-Key": mid}
        )
        assert res.status_code == 201, res.text
    return mid, datetime.fromisoformat(data["ends_at"])


@pytest.fixture
def club(api):
    group = create_group(api)["id"]
    join(api, group)
    return group, group_card(api, group, "owner"), group_card(api, group, "member")


def send(api, mid, peer, key="create", tags=("kind",), **extra):
    return api.post(
        f"/api/meetings/{mid}/encouragements",
        headers={"Idempotency-Key": key},
        json={"recipient_card_id": peer["id"], "tags": list(tags), **extra},
    )


def test_eligibility_and_window(api, club, monkeypatch, db_engine):
    group, mine, peer = club
    mid, end = group_meeting(api, group)
    one = timedelta(microseconds=1)
    monkeypatch.setattr(encouragements, "now", lambda: end)
    assert send(api, mid, peer).status_code == 403
    personal_card = personal(api, "member")
    assert "top_encouragement_tags" not in personal_card
    exchange(api, mine, personal_card)
    assert send(api, mid, personal_card).status_code == 403
    assert send(api, mid, peer).status_code == 403
    exchange(api, mine, peer)
    assert send(api, mid, mine).status_code == 403
    assert send(api, create_meeting(api)["id"], peer).status_code == 403
    canceled, _ = group_meeting(api, group)
    response = api.patch(
        f"/api/meetings/{canceled}", json={"status": "canceled", "cancel_reason": "합성 취소"}
    )
    assert response.status_code == 200
    assert send(api, canceled, peer).status_code == 403
    for tags in [[], ["kind", "kind"], ["invalid"]]:
        assert send(api, mid, peer, tags=tags).status_code == 422
    with Session(db_engine) as session, session.begin():
        member = session.scalar(
            select(Registration).where(
                Registration.meeting_id == UUID(mid), Registration.senior_id == ids("member")[1]
            )
        )
        member.status = "canceled"
        registration_id = member.id
    assert send(api, mid, peer).status_code == 403
    with Session(db_engine) as session, session.begin():
        session.get(Registration, registration_id).status = "confirmed"
    for at in [end - one, end + timedelta(hours=72) + one]:
        monkeypatch.setattr(encouragements, "now", lambda: at)
        assert send(api, mid, peer).status_code == 409
    monkeypatch.setattr(encouragements, "now", lambda: end)
    res = send(api, mid, peer)
    assert res.status_code == 201, res.text
    path = "/api/encouragements/" + res.json()["id"]

    def edit(who="owner", version=1):
        return api.put(
            path, headers={**auth(who), "If-Match": f'"{version}"'}, json={"tags": ["positive"]}
        )

    assert edit("member").status_code == 404
    monkeypatch.setattr(encouragements, "now", lambda: end + timedelta(hours=72))
    assert edit().status_code == 200
    assert edit().status_code == 409
    monkeypatch.setattr(encouragements, "now", lambda: end + timedelta(hours=72) + one)
    assert edit(version=2).status_code == 409
    assert api.delete(path, headers=auth("member")).status_code == 404
    assert api.delete(path, headers=auth("other")).status_code == 404
    for _ in range(2):
        assert api.delete(path).status_code == 204
    monkeypatch.setattr(encouragements, "now", lambda: end)
    assert send(api, mid, peer, key="new").status_code == 409
    assert send(api, mid, peer).status_code == 404


def test_rank_scope_reports_and_moderation(api, club, monkeypatch, db_engine):
    group, mine, peer = club
    exchange(api, mine, peer)
    second_group = create_group(api)["id"]
    join(api, second_group)
    second_peer = group_card(api, second_group, "member")
    exchange(api, group_card(api, second_group, "owner"), second_peer)
    first, end = group_meeting(api, group)
    second, end2 = group_meeting(api, group)
    at = max(end, end2)
    monkeypatch.setattr(encouragements, "now", lambda: at)
    assert send(api, first, second_peer).status_code == 403
    res = send(api, first, peer, tags=["kind", "sociable", "fun"], text="합성 응원")
    assert res.status_code == 201, res.text
    original = res.json()
    path = "/api/encouragements/" + original["id"]
    at += timedelta(seconds=1)
    second_message = send(api, second, peer, key="two", tags=["kind", "positive"]).json()

    def rank(card):
        return api.get("/api/cards/" + card["id"], headers=auth("member")).json()[
            "top_encouragement_tags"
        ]

    inbox = f"/api/groups/{group}/me/encouragements"

    def received(**params):
        return api.get(inbox, headers=auth("member"), params=params).json()

    assert rank(peer) == ["kind", "positive", "fun"]
    assert rank(second_peer) == []
    public_card = api.get("/api/cards/" + peer["id"]).json()
    assert public_card["top_encouragement_tags"] == rank(peer)
    assert {"items", "tag_counts", "text"}.isdisjoint(public_card)
    other_mid, other_end = group_meeting(api, second_group)
    at = max(at, other_end)
    assert (
        send(api, other_mid, second_peer, key="other-group", tags=["admirable"]).status_code == 201
    )
    assert rank(second_peer) == ["admirable"]
    assert api.get(inbox, headers=auth("other")).status_code == 403
    page = received(limit=1)
    assert len(page["tag_counts"]) == 9
    assert sum(t["count"] for t in page["tag_counts"]) == 5
    assert page["items"] == [second_message]
    next_page = received(limit=1, cursor=page["next_cursor"])
    assert next_page["items"] == [original] and next_page["tag_counts"] == page["tag_counts"]
    at += timedelta(seconds=1)
    edit = api.put(
        path, headers={"If-Match": '"1"'}, json={"tags": ["kind", "fun", "warmhearted"]}
    ).json()
    assert edit["created_at"] == original["created_at"] and edit["text"] is None
    assert rank(peer) == ["kind", "warmhearted", "positive"]
    with Session(db_engine) as session, session.begin(), pytest.raises(ValueError):
        moderate(session, "delete", UUID(original["id"]), 2)
    at += timedelta(days=5)
    assert api.post(path + "/reports").status_code == 404
    for _ in range(2):
        assert api.post(path + "/reports", headers=auth("member")).status_code == 204
    assert len(received()["items"]) == 2
    with Session(db_engine) as session, session.begin():
        assert session.scalar(select(func.count()).select_from(EncouragementReport)) == 1
        assert moderate(session, "list") == original["id"]
        assert "warmhearted" in moderate(session, "show", UUID(original["id"]))
        with pytest.raises(ValueError):
            moderate(session, "delete", UUID(original["id"]), 1)
        moderate(session, "delete", UUID(original["id"]), 2)
    assert rank(peer) == ["kind", "positive"]
    assert received()["items"] == [second_message]
    assert api.delete("/api/encouragements/" + second_message["id"]).status_code == 204
    assert sum(t["count"] for t in received()["tag_counts"]) == 0
    assert rank(peer) == []
    assert rank(second_peer) == ["admirable"]


def test_concurrent_creation_edit_and_delete(api, club, monkeypatch):
    group, mine, peer = club
    exchange(api, mine, peer)
    mid, end = group_meeting(api, group)
    monkeypatch.setattr(encouragements, "now", lambda: end + timedelta(hours=72))
    with ThreadPoolExecutor(3) as pool:
        responses = list(pool.map(lambda key: send(api, mid, peer, key), ["one", "one", "two"]))
    winner = next(r for r in responses if r.status_code == 201)
    assert all(r.json()["id"] == winner.json()["id"] for r in responses if r.status_code == 201)
    assert responses[0].status_code == responses[1].status_code
    assert {r.status_code for r in responses} == {201, 409}
    key = "one" if responses[0].status_code == 201 else "two"
    assert send(api, mid, peer, key, tags=["fun"]).status_code == 409
    path = "/api/encouragements/" + winner.json()["id"]
    with ThreadPoolExecutor(2) as pool:
        edit = pool.submit(
            api.put, path, headers={"If-Match": '"1"'}, json={"tags": ["warmhearted"]}
        )
        removal = pool.submit(api.delete, path)
        assert edit.result().status_code in (200, 404)
        assert removal.result().status_code == 204
    assert send(api, mid, peer, key).status_code == 404
    assert (
        api.get(f"/api/groups/{group}/me/encouragements", headers=auth("member")).json()["items"]
        == []
    )


def test_report_review_racing_edit_and_membership_loss(api, club, monkeypatch, db_engine):
    group, mine, peer = club
    exchange(api, mine, peer)
    mid, end = group_meeting(api, group)
    monkeypatch.setattr(encouragements, "now", lambda: end)
    message = send(api, mid, peer).json()
    path = "/api/encouragements/" + message["id"]
    assert api.post(path + "/reports", headers=auth("member")).status_code == 204

    def review_delete():
        with Session(db_engine) as session, session.begin():
            try:
                moderate(session, "delete", UUID(message["id"]), 1)
            except ValueError:
                return False
            return True

    with ThreadPoolExecutor(2) as pool:
        review = pool.submit(review_delete)
        edit = pool.submit(api.put, path, headers={"If-Match": '"1"'}, json={"tags": ["fun"]})
        assert (review.result(), edit.result().status_code) in {(True, 404), (False, 200)}
    assert (
        api.delete(f"/api/groups/{group}/memberships/me", headers=auth("member")).status_code == 204
    )
    assert (
        api.get(f"/api/groups/{group}/me/encouragements", headers=auth("member")).status_code == 403
    )
    assert send(api, mid, peer).status_code == 403
    assert api.delete(path).status_code == 204


def test_author_delete_promotes_fourth_tag(api, club, monkeypatch):
    group, mine, peer = club
    exchange(api, mine, peer)
    first, end = group_meeting(api, group)
    second, later = group_meeting(api, group)
    at = max(end, later)
    monkeypatch.setattr(encouragements, "now", lambda: at)
    assert send(api, first, peer, tags=["positive", "kind", "warmhearted"]).status_code == 201
    at += timedelta(seconds=1)
    newest = send(api, second, peer, key="latest", tags=["fun"])
    assert newest.status_code == 201
    card_path = "/api/cards/" + peer["id"]
    assert api.get(card_path).json()["top_encouragement_tags"] == ["fun", "kind", "positive"]
    assert api.delete("/api/encouragements/" + newest.json()["id"]).status_code == 204
    assert api.get(card_path).json()["top_encouragement_tags"] == [
        "kind",
        "positive",
        "warmhearted",
    ]
