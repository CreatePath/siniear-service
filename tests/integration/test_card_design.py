from sqlalchemy.orm import Session

from app.db.models.identity import Senior
from scripts.seed_dev import ids
from tests.integration.conftest import auth
from tests.integration.test_interviews import ready
from tests.integration.test_personal_cards import confirmation


def personal(api, who):
    res = api.post(
        "/api/me/cards",
        headers=auth(who),
        json={"template_key": "fresh_start", "visible_fields": ["experience"]},
    )
    assert res.status_code == 201, res.text
    return res.json()


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
