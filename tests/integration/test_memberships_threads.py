from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.membership import JoinRequest, Membership, MembershipTitle
from tests.integration.conftest import auth, join
from tests.integration.test_groups_meetings import create_group, meeting_data


def test_review_membership_title_and_thread_access(api, db_engine):
    group = create_group(api)
    group_path = f"/api/groups/{group['id']}"
    body = meeting_data()
    del body["region_code"]
    meeting = api.post(group_path + "/meetings", json=body).json()
    meeting_path = f"/api/meetings/{meeting['id']}"
    member = auth("member")
    key = {**member, "Idempotency-Key": "apply"}
    path = group_path + "/join-requests"
    request = api.post(path, headers=key).json()
    review = path + "/" + request["id"]
    assert api.get(group_path, headers=member).json()["my_membership_status"] == "pending"
    assert api.post(meeting_path + "/registrations", headers=key).status_code == 403
    assert api.get(path, headers=member).status_code == 403
    assert api.patch(review, json={"status": "approved"}, headers=member).status_code == 403
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: api.patch(review, json={"status": "approved"}), range(2)))
    assert [r.status_code for r in results] == [200, 200]
    assert api.patch(review, json={"status": "rejected"}).status_code == 409
    assert api.get(group_path).json()["member_count"] == 2
    assert api.get(meeting_path, headers=member).json()["participant_count"] == 0
    (membership,) = api.get("/api/me/memberships", headers=member).json()["items"]
    card = "/api/cards/" + membership["card_id"]
    titles = f"/api/me/memberships/{membership['id']}/titles"
    assert api.get(titles, headers=member).json() == {"items": []}
    with Session(db_engine) as session, session.begin():
        award = MembershipTitle(
            membership_id=UUID(membership["id"]), label="합성 칭호", evidence_ref="synthetic"
        )
        session.add(award)
        session.flush()
        award_id = str(award.id)
    assert api.get(titles, headers=member).json()["items"] == [
        {"id": award_id, "label": "합성 칭호"}
    ]
    edit = api.patch(
        card,
        headers={**member, "If-Match": '"1"'},
        json={"selected_title_id": award_id, "visible_fields": ["title"]},
    )
    assert edit.json()["fields"] == {"title": "합성 칭호"}
    assert api.delete(group_path + "/memberships/me", headers=member).status_code == 204
    for url in (card, titles):
        assert api.get(url, headers=member).status_code == 404
    join(api, group["id"])
    (new,) = api.get("/api/me/memberships", headers=member).json()["items"]
    assert new["id"] != membership["id"]
    assert (
        api.patch(
            "/api/cards/" + new["card_id"],
            headers={**member, "If-Match": '"1"'},
            json={"selected_title_id": award_id},
        ).status_code
        == 422
    )


@pytest.mark.parametrize("finish", ["reject", "close", "withdraw"])
def test_review_races_with_resolution(api, db_engine, finish):
    group = create_group(api)
    path = "/api/groups/" + group["id"]
    headers = {**auth("member"), "Idempotency-Key": "join"}
    applied = api.post(path + "/join-requests", headers=headers).json()
    url = path + "/join-requests/" + applied["id"]

    def competing():
        if finish == "reject":
            return api.patch(url, json={"status": "rejected"})
        if finish == "close":
            return api.patch(path, json={"status": "closed"})
        return api.delete("/api/users/me", headers=auth("member"))

    with ThreadPoolExecutor(2) as pool:
        approved = pool.submit(api.patch, url, json={"status": "approved"})
        other = pool.submit(competing)
        assert approved.result().status_code in (200, 409)
        assert other.result().status_code in (200, 204, 409)
    with Session(db_engine) as session:
        row = session.get(JoinRequest, UUID(applied["id"]))
        active = session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.senior_id == row.senior_id, Membership.left_at.is_(None))
        )
        assert active == int(finish == "reject" and row.status == "approved")
        assert (row.membership_id is not None) == (row.status == "approved")
        if row.status == "rejected":
            retried = api.post(
                path + "/join-requests", headers={**headers, "Idempotency-Key": "again"}
            )
            assert retried.status_code == 201 and retried.json()["id"] != applied["id"]
