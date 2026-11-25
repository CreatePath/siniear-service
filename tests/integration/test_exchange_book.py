from concurrent.futures import ThreadPoolExecutor

from tests.integration.conftest import auth


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
