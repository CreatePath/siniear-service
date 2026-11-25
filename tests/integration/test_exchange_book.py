from concurrent.futures import ThreadPoolExecutor

from tests.integration.conftest import auth
from tests.integration.test_groups_meetings import create_group


def personal(api, who):
    res = api.post(
        "/api/me/cards",
        headers=auth(who),
        json={"template_key": "fresh_start", "visible_fields": ["experience"]},
    )
    assert res.status_code == 201, res.text
    return res.json()


def offer(api, who, card):
    res = api.post("/api/exchange-offers", headers=auth(who), json={"card_id": card["id"]})
    assert res.status_code == 201
    return res.json()["token"]


def test_exchange_privacy_book_and_revocation(api):
    owner, member = personal(api, "owner"), personal(api, "member")
    owner_path = "/api/cards/" + owner["id"]
    other = auth("member")
    path = "/api/me/card-book"
    favorite = path + "/" + owner["id"] + "/favorite"
    senior = api.get("/api/users/me").json()["senior_id"]
    assert (
        api.patch(
            "/api/seniors/" + senior,
            headers={"If-Match": '"1"'},
            json={"experience": "합성 경력", "job_title": "비공개 직무"},
        ).status_code
        == 200
    )
    token = offer(api, "owner", owner)
    preview = api.post("/api/exchange-offers/preview", headers=other, json={"token": token}).json()[
        "card"
    ]
    assert preview["fields"] == {"experience": "합성 경력"}
    assert {"version", "visible_fields", "selected_title_id"}.isdisjoint(preview)
    assert api.get(owner_path, headers=other).status_code == 404
    assert api.get(path, headers=other).json()["total_count"] == 0
    assert api.put(favorite, headers=other, json={"is_favorite": True}).status_code == 404
    payload = {"token": token, "card_id": member["id"], "exchange_method": "qr"}

    def accept(key):
        return api.post("/api/exchanges", headers={**other, "Idempotency-Key": key}, json=payload)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(accept, ["one", "two"]))
    assert sorted(r.status_code for r in results) == [201, 409]
    winner = "one" if results[0].status_code == 201 else "two"
    assert accept(winner).status_code == 201
    assert api.get(owner_path, headers=other).json() == preview
    assert api.get("/api/me/exchanges").json()["items"][0]["peer_card"]["id"] == member["id"]
    for _ in range(2):
        assert api.put(favorite, headers=other, json={"is_favorite": True}).status_code == 200
    match = api.get(path, headers=other, params={"keyword": " 경력 ", "favorite_only": True}).json()
    assert match["total_count"] == match["favorite_count"] == 1
    assert match["items"][0]["exchange_method"] == "qr"
    assert api.get(path).json()["favorite_count"] == 0
    assert (
        api.patch(owner_path, headers={"If-Match": '"1"'}, json={"visible_fields": []}).status_code
        == 200
    )
    assert accept(winner).json()["peer_card"]["fields"] == {}
    assert api.get(path, headers=other, params={"keyword": "경력"}).json()["total_count"] == 0
    assert api.delete(owner_path, headers={"If-Match": '"2"'}).status_code == 204
    assert api.get(path, headers=other).json()["total_count"] == 0
    assert api.get(owner_path, headers=other).status_code == 404
    assert accept(winner).status_code == 404


def test_group_exchange_and_duplicate_received_card(api):
    first = personal(api, "owner")
    second = personal(api, "member")
    group = create_group(api)
    club = next(c for c in api.get("/api/me/cards").json()["items"] if c["kind"] == "group")
    for i, mine in enumerate([first, club, club]):
        token = offer(api, "member", second)
        res = api.post(
            "/api/exchanges",
            headers={"Idempotency-Key": str(i)},
            json={"token": token, "card_id": mine["id"]},
        )
        assert res.status_code == [201, 201, 200][i], res.text
    assert api.get("/api/me/card-book").json()["total_count"] == 1
    page = api.get("/api/me/card-book?limit=1", headers=auth("member")).json()
    assert page["total_count"] == 2 and len(page["items"]) == 1
    cursor = page["next_cursor"]
    next_page = api.get(
        "/api/me/card-book", headers=auth("member"), params={"cursor": cursor, "limit": 1}
    ).json()
    assert next_page["next_cursor"] is None
    assert api.get("/api/me/card-book", params={"cursor": cursor}).status_code == 422
    assert api.patch("/api/groups/" + group["id"], json={"status": "closed"}).status_code == 200
    assert api.get("/api/me/card-book", headers=auth("member")).json()["total_count"] == 1
    assert api.get("/api/cards/" + club["id"], headers=auth("member")).status_code == 404
    assert api.delete("/api/users/me").status_code == 204
    assert api.get("/api/me/card-book", headers=auth("member")).json()["items"] == []
