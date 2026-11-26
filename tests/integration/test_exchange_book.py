from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

from app.db.models import Senior
from scripts.seed_dev import ids
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


def test_book_search_uses_name_selected_for_display(api, db_engine):
    peer, mine = personal(api, "owner"), personal(api, "member")
    with Session(db_engine) as session, session.begin():
        session.get(Senior, ids("owner")[1]).name = "합성실명"
    token = offer(api, "owner", peer)
    assert (
        api.post(
            "/api/exchanges",
            headers={**auth("member"), "Idempotency-Key": "exchange"},
            json={"token": token, "card_id": mine["id"]},
        ).status_code
        == 201
    )

    def matches(keyword):
        response = api.get("/api/me/card-book", headers=auth("member"), params={"keyword": keyword})
        assert response.status_code == 200
        return [item["peer_card"]["id"] for item in response.json()["items"]]

    assert matches(peer["name"]) == [peer["id"]]
    assert matches("실명") == []
    assert (
        api.patch(
            f"/api/seniors/{ids('owner')[1]}",
            headers={"If-Match": '"1"'},
            json={"card_name_mode": "name"},
        ).status_code
        == 200
    )
    assert matches(" 실명 ") == [peer["id"]]
    assert matches(peer["name"]) == []


def test_book_search_by_received_cards_current_group(api):
    book = "/api/me/card-book"
    personal_peer, mine = personal(api, "owner"), personal(api, "member")
    group_names = ["달빛 Walk_100%", "토요 walk"]
    for name in group_names:
        assert (
            api.post("/api/groups", json={"name": name, "region_code": "11110"}).status_code == 201
        )
    cards = api.get("/api/me/cards").json()["items"]
    group_cards = {c["group"]["name"]: c for c in cards if c["kind"] == "group"}
    first, second = (group_cards[name] for name in group_names)
    for card in [first, personal_peer, second]:
        assert (
            api.post(
                "/api/exchanges",
                headers={**auth("member"), "Idempotency-Key": card["id"]},
                json={"token": offer(api, "owner", card), "card_id": mine["id"]},
            ).status_code
            == 201
        )

    def search(keyword, who="member", **params):
        response = api.get(book, headers=auth(who), params={"keyword": keyword, **params})
        assert response.status_code == 200, response.text
        return response.json()

    empty = {"items": [], "next_cursor": None, "total_count": 0, "favorite_count": 0}
    assert (
        api.put(
            f"{book}/{first['id']}/favorite", headers=auth("member"), json={"is_favorite": True}
        ).status_code
        == 200
    )
    page = search("  wAlK  ", limit=1)
    assert (page["total_count"], page["favorite_count"]) == (2, 1)
    assert [i["peer_card"]["id"] for i in page["items"]] == [second["id"]]
    assert page["next_cursor"]
    next_page = search("wAlK", limit=1, cursor=page["next_cursor"])
    assert [i["peer_card"]["id"] for i in next_page["items"]] == [first["id"]]
    assert next_page["next_cursor"] is None
    stars = search("walk", favorite_only=True)
    assert (stars["total_count"], stars["favorite_count"]) == (2, 1)
    assert [i["peer_card"]["id"] for i in stars["items"]] == [first["id"]]
    for keyword in ("_", "%", "달빛"):
        assert [i["peer_card"]["id"] for i in search(keyword)["items"]] == [first["id"]]
    assert search("달빛", who="other") == empty
    group_path = "/api/groups/" + first["group"]["id"]
    assert api.patch(group_path, json={"name": "새벽 모임"}).status_code == 200
    assert search("달빛") == empty
    assert search("새벽")["favorite_count"] == 1
    assert api.patch(group_path, json={"status": "closed"}).status_code == 200
    assert search("새벽") == empty
