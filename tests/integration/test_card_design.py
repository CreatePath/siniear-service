from datetime import UTC, datetime, timedelta
from io import BytesIO

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.exchange import ExchangeOffer
from app.db.models.identity import Senior
from scripts.seed_dev import ids
from tests.integration.conftest import auth
from tests.integration.test_exchange_book import personal
from tests.integration.test_interviews import ready
from tests.integration.test_personal_cards import confirmation


def test_profile_design_preview_confirm_delete_recreate(api, db_engine):
    path = f"/api/seniors/{ids('owner')[1]}"
    version = {"If-Match": '"1"'}
    for invalid in [
        {"name": "임의 이름"},
        {"card_name_mode": "name"},
        {"activity_style": ["social"]},
        {"activity_style": "unknown"},
    ]:
        assert api.patch(path, headers=version, json=invalid).status_code == 422
    assert api.get(path).json()["name"] is None
    with Session(db_engine) as session, session.begin():
        session.get(Senior, ids("owner")[1]).name = "인증 이름"
    row = ready(api)
    body = {
        **confirmation(row),
        "profile": {
            "nickname": "별명",
            "card_name_mode": "name",
            "activity_style": "social",
            "job_title": "직무",
        },
        "color_code": "#2062D1",
        "visible_fields": ["job_title", "region_code"],
        "template_key": "fresh_start",
    }
    interview = f"/api/interviews/{row['id']}"
    preview = api.post(interview + "/preview", json=body).json()
    assert preview["name"] == "인증 이름" and preview["fields"] == {
        "job_title": "직무",
        "region_code": "11110",
    }
    assert api.get(path).json()["activity_style"] is None
    key = {"Idempotency-Key": "confirm"}
    result = api.post(interview + "/confirm", json=body, headers=key).json()
    card = result["card"]
    assert all(card[k] == v for k, v in preview.items()) and card["color_code"] == "#2062D1"
    assert result["profile"]["activity_style"] == "social"
    url = "/api/cards/" + card["id"]
    assert api.patch(url, headers=version, json={"color_code": None}).status_code == 422
    assert (
        api.patch(url, headers=version, json={"template_key": "classic"}).json()["color_code"]
        == "#2062D1"
    )
    assert (
        api.patch(
            path,
            headers={"If-Match": '"2"'},
            json={"card_name_mode": "nickname", "activity_style": None},
        ).status_code
        == 200
    )
    assert api.get(url).json()["name"] == "별명"
    assert api.delete(url, headers={"If-Match": '"2"'}).status_code == 204
    personal(api, "owner")
    assert api.post(interview + "/confirm", json=body, headers=key).status_code == 409


def test_offer_photos_and_badge_ownership(api, db_engine):
    image = BytesIO()
    Image.new("RGB", (2, 2)).save(image, "PNG")
    file = {"file": ("image.png", image.getvalue(), "image/png")}
    badge = api.post("/api/group-badges", files=file).json()["badge_id"]
    photo = api.post("/api/me/profile-photos", files=file).json()["photo_id"]
    group = {
        "name": "합성 모임",
        "region_code": "SEOUL",
        "badge_id": badge,
        "activity_goals": ["목공 나눔"],
    }
    assert api.post("/api/groups", headers=auth("other"), json=group).status_code == 422
    assert api.post("/api/groups", json={**group, "badge_id": photo}).status_code == 422
    result = api.post("/api/groups", json=group)
    assert result.status_code == 201
    assert (
        api.get(result.json()["badge_url"], headers=auth("other")).headers["content-type"]
        == "image/jpeg"
    )
    profile = f"/api/seniors/{ids('owner')[1]}"
    version = {"If-Match": '"1"'}
    assert api.patch(profile, headers=version, json={"photo_id": badge}).status_code == 422
    assert api.patch(profile, headers=version, json={"photo_id": photo}).status_code == 200
    path = f"/api/seniors/{ids('other')[1]}"
    assert (
        api.patch(
            path, headers={**version, **auth("other")}, json={"want_to_learn": ["목공"]}
        ).status_code
        == 200
    )
    reasons = api.get("/api/me/group-recommendations", headers=auth("other")).json()["items"][0][
        "reasons"
    ]
    assert any("목공 나눔" in r for r in reasons)
    owner = personal(api, "owner")
    card = "/api/cards/" + owner["id"]
    assert (
        api.patch(card, headers=version, json={"visible_fields": ["photo_url"]}).status_code == 200
    )
    other = personal(api, "other")
    offer = api.post("/api/exchange-offers", json={"card_id": owner["id"]}).json()
    token = {"token": offer["token"]}
    assert api.post("/api/exchange-offers/preview", json=token).status_code == 409
    recipient = auth("other")
    preview = api.post("/api/exchange-offers/preview", headers=recipient, json=token).json()
    preview_url = preview["card"]["fields"]["photo_url"]
    assert api.get(preview_url, headers=recipient).status_code == 422
    assert (
        api.get(preview_url, headers={**recipient, "X-Exchange-Token": offer["token"]}).status_code
        == 200
    )
    key = {**recipient, "Idempotency-Key": "accept"}
    assert (
        api.post("/api/exchanges", headers=key, json={**token, "card_id": owner["id"]}).status_code
        == 403
    )
    paired = api.post("/api/exchanges", headers=key, json={**token, "card_id": other["id"]}).json()
    photo_url = paired["peer_card"]["fields"]["photo_url"]
    assert api.get(photo_url, headers=recipient).status_code == 200
    assert api.get(photo_url, headers=auth("member")).status_code == 404
    assert (
        api.patch(card, headers={"If-Match": '"2"'}, json={"visible_fields": []}).status_code == 200
    )
    assert api.get(photo_url, headers=recipient).status_code == 404
    expired = api.post("/api/exchange-offers", json={"card_id": owner["id"]}).json()
    with Session(db_engine) as session, session.begin():
        row = session.scalar(select(ExchangeOffer).where(ExchangeOffer.consumed_at.is_(None)))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert (
        api.post(
            "/api/exchange-offers/preview", headers=recipient, json={"token": expired["token"]}
        ).status_code
        == 409
    )
