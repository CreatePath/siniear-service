from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.db.models.membership import Membership
from tests.integration.conftest import auth, join
from tests.integration.test_community import create_post
from tests.integration.test_exchange_book import offer
from tests.integration.test_groups_meetings import create_group, create_meeting, meeting_data
from tests.integration.test_registrations import cancel, signup


def period(api, name):
    (membership,) = api.get("/api/me/memberships", headers=auth(name)).json()["items"]
    return membership


def titles(api, membership, name):
    response = api.get(f"/api/me/memberships/{membership['id']}/titles", headers=auth(name))
    assert response.status_code == 200
    return {item["label"]: item["tier"] for item in response.json()["items"]}


def group_meeting(api, group):
    data = meeting_data()
    del data["region_code"]
    response = api.post(f"/api/groups/{group['id']}/meetings", json=data)
    assert response.status_code == 201
    return response.json()


def test_posts_accrue_during_one_period_and_survive_delete(api):
    group = create_group(api)
    create_post(api, group)
    join(api, group["id"])
    member = period(api, "member")
    owner = period(api, "owner")
    first = create_post(api, group)
    assert api.delete("/api/posts/" + first["id"], headers=auth("member")).status_code == 204
    for _ in range(8):
        create_post(api, group)
    assert titles(api, member, "member") == {"신규 회원": "silver"}
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _: create_post(api, group), range(2)))
    assert titles(api, member, "member") == {"신규 회원": "silver", "이야기꾼": "gold"}
    for _ in range(88):
        create_post(api, group)
    assert "대문호" not in titles(api, member, "member")
    create_post(api, group)
    assert titles(api, member, "member")["대문호"] == "diamond"
    assert titles(api, owner, "owner") == {"신규 회원": "silver"}
    assert (
        api.delete(f"/api/groups/{group['id']}/memberships/me", headers=auth("member")).status_code
        == 204
    )
    join(api, group["id"], key="rejoin")
    assert titles(api, period(api, "member"), "member") == {"신규 회원": "silver"}


@pytest.mark.parametrize(
    "prior,label,tier",
    [(0, "새로운 이웃", "silver"), (9, "두루 아는 이웃", "gold"), (99, "마당발", "diamond")],
)
def test_exchange_threshold_both_cards_and_replay(api, db_engine, prior, label, tier):
    group = create_group(api)
    join(api, group["id"])
    owner, member = period(api, "owner"), period(api, "member")
    with Session(db_engine) as session, session.begin():
        for m in (member, owner):
            session.get(Membership, UUID(m["id"])).exchange_count = prior
    peer = {"id": owner["card_id"]}
    token = offer(api, "owner", peer)
    headers = {**auth("member"), "Idempotency-Key": "accept"}
    payload = {"card_id": member["card_id"], "token": token}
    assert (
        api.post(
            "/api/exchange-offers/preview", headers=auth("member"), json={"token": token}
        ).status_code
        == 200
    )
    assert label not in titles(api, member, "member")
    for _ in range(2):
        result = api.post("/api/exchanges", headers=headers, json=payload)
        assert result.status_code == 201
        assert result.json()["peer_card"]["fields"] == {}
    payload["token"] = offer(api, "owner", peer)
    headers["Idempotency-Key"] = "again"
    assert api.post("/api/exchanges", headers=headers, json=payload).status_code == 200
    owner_titles = api.get(f"/api/me/memberships/{owner['id']}/titles").json()["items"]
    award = next(item for item in owner_titles if item["label"] == label)
    card_path = "/api/cards/" + owner["card_id"]
    assert (
        api.patch(
            card_path,
            headers={"If-Match": '"1"'},
            json={"selected_title_id": award["id"], "visible_fields": ["title"]},
        ).status_code
        == 200
    )
    peer_card = api.get(card_path, headers=auth("member")).json()
    assert peer_card["fields"] == {"title": label}
    assert {"tier", "selected_title_id", "evidence_ref"}.isdisjoint(peer_card)
    assert (
        api.patch(card_path, headers={"If-Match": '"2"'}, json={"visible_fields": []}).status_code
        == 200
    )
    assert api.get(card_path, headers=auth("member")).json()["fields"] == {}
    for m, name in ((member, "member"), (owner, "owner")):
        assert titles(api, m, name)[label] == tier
        with Session(db_engine) as session:
            assert session.get(Membership, UUID(m["id"])).exchange_count == prior + 1


def test_registration_titles_count_distinct_applications_in_this_period(api):
    group = create_group(api)
    join(api, group["id"])
    member = period(api, "member")
    standalone = create_meeting(api)
    assert signup(api, standalone).status_code == 201
    assert titles(api, member, "member") == {"신규 회원": "silver"}
    full = group_meeting(api, group)
    join(api, group["id"], "other")
    assert signup(api, full, "owner").status_code == 201
    assert signup(api, full, "other").status_code == 201
    assert signup(api, full, key="full").json()["error"]["code"] == "MEETING_FULL"
    assert titles(api, member, "member") == {"신규 회원": "silver"}
    for i in range(1, 101):
        meeting = group_meeting(api, group)
        if i == 1:
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda k: signup(api, meeting, key=k), ["one", "two"]))
            assert sorted(r.status_code for r in results) == [200, 201]
            reg = results[0].json()
            assert signup(api, meeting, key="one").json() == reg
            assert cancel(api, meeting, reg, 1).status_code == 204
            assert titles(api, member, "member")["새로운 얼굴"] == "silver"
            assert signup(api, meeting, key="again").status_code == 200
        else:
            assert signup(api, meeting, key=str(i)).status_code == 201
        if i in (1, 9, 10, 99, 100):
            expected = {"신규 회원": "silver", "새로운 얼굴": "silver"}
            if i >= 10:
                expected["친숙한 얼굴"] = "gold"
            if i >= 100:
                expected["터줏대감"] = "diamond"
            assert titles(api, member, "member") == expected
    assert (
        api.delete(f"/api/groups/{group['id']}/memberships/me", headers=auth("member")).status_code
        == 204
    )
    join(api, group["id"], key="rejoin")
    new = period(api, "member")
    # A previously confirmed seat and a replay carry no new application into the new period.
    assert signup(api, meeting, key="old-seat").status_code == 200
    assert titles(api, new, "member") == {"신규 회원": "silver"}
    assert cancel(api, meeting, signup(api, meeting, key="old-seat").json(), 1).status_code == 204
    assert signup(api, meeting, key="new-application").status_code == 200
    assert titles(api, new, "member") == {"신규 회원": "silver", "새로운 얼굴": "silver"}
