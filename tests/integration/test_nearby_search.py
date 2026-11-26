from sqlalchemy.orm import Session

from app.db.models import Senior
from scripts.seed_dev import ids
from tests.integration.test_groups_meetings import auth, create_meeting, meeting_data


def group(api, code, name="주말 모임", interests=("산책", "그림")):
    response = api.post(
        "/api/groups", json={"region_code": code, "name": name, "interests": interests}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_group_search_default_and_named_region(api):
    path = "/api/search/groups"
    local = [group(api, code) for code in ("11110", "11290", "11410", "11140")]
    nearby = [group(api, code) for code in ("11590", "11620", "1117010100", "11560")]
    inactive = group(api, "11590")
    api.patch(f"/api/groups/{inactive}", json={"status": "closed"}).raise_for_status()
    group(api, "11680")
    group(api, "11590", interests=("운동",))
    result = api.get(path).json()
    assert {item["id"] for item in result["items"]} == set(local)
    params = {"keyword": "그림 서울 동작구", "category": "walk", "limit": 2}
    page = api.get(path, params=params).json()
    assert [r["region_code"] for r in page["regions"]] == ["11590", "11620", "11170", "11560"]
    assert page["regions"][0]["name"] == "서울특별시 동작구"
    assert page["total_count"] == 4
    cursor = page["next_cursor"]
    following = api.get(path, params={**params, "cursor": cursor}).json()
    assert {r["id"] for r in page["items"] + following["items"]} == set(nearby)
    assert following["next_cursor"] is None
    for changes in ({"category": "hobby"}, {"keyword": "종로구 그림"}):
        assert api.get(path, params={**params, **changes, "cursor": cursor}).status_code == 422
    assert (
        api.get(path, params={**params, "cursor": cursor}, headers=auth("member")).status_code
        == 422
    )
    assert api.get(path, params={"keyword": "동작구 %"}).json()["total_count"] == 0
    assert api.get(path, headers={"Authorization": ""}).status_code == 401


def test_flash_search_category_and_group_schedule_visibility(api):
    path = "/api/search/meetings"
    flash = create_meeting(api, region_code="11620", title="수채화 교실", category="hobby")
    legacy = create_meeting(api, region_code="11590", title="수채화 기초")
    create_meeting(api, region_code="11680", title="수채화 교실", category="hobby")
    canceled = create_meeting(api, region_code="11590")
    api.patch(
        f"/api/meetings/{canceled['id']}", json={"status": "canceled", "cancel_reason": "휴무"}
    ).raise_for_status()
    club = group(api, "11590")
    data = meeting_data(title="수채화 회원 일정", category="hobby")
    del data["region_code"]
    api.post(f"/api/groups/{club}/meetings", json=data).raise_for_status()
    for actor in ("owner", "member"):
        rows = api.get(path, params={"keyword": "동작구"}, headers=auth(actor)).json()["items"]
        assert {r["id"] for r in rows} == {flash["id"], legacy["id"]}
    page = api.get(path, params={"keyword": "동작구 수채", "category": "hobby"}).json()
    assert [(r["id"], r["category"]) for r in page["items"]] == [(flash["id"], "hobby")]
    assert api.get(path, params={"keyword": "동작구 취미"}).json()["total_count"] == 1
    api.patch(f"/api/meetings/{legacy['id']}", json={"category": "exercise"}).raise_for_status()
    assert (
        api.get(path, params={"keyword": "동작구", "category": "exercise"}).json()["total_count"]
        == 1
    )


def test_ambiguous_district_and_legacy_code(api, db_engine):
    path = "/api/search/groups"
    assert api.get(path, params={"keyword": "중구"}).json()["regions"][0]["region_code"] == "11140"
    with Session(db_engine) as session, session.begin():
        session.get(Senior, ids("owner")[1]).region_code = "legacy"
    assert api.get(path).json()["error"]["code"] == "SEARCH_REGION_REQUIRED"
    assert api.get(path, params={"keyword": "중구"}).json()["error"]["code"] == "AMBIGUOUS_REGION"
    assert (
        api.get(path, params={"keyword": "부산 중구"}).json()["regions"][0]["region_code"]
        == "26110"
    )


def test_cursor_follows_current_profile_region_and_tab(api, db_engine):
    for _ in range(2):
        group(api, "11110")
    path = "/api/search/groups"
    cursor = api.get(path, params={"limit": 1}).json()["next_cursor"]
    assert (
        api.get("/api/search/meetings", params={"cursor": cursor}).json()["error"]["code"]
        == "INVALID_CURSOR"
    )
    with Session(db_engine) as session, session.begin():
        session.get(Senior, ids("owner")[1]).region_code = "11590101"
    assert api.get(path, params={"cursor": cursor}).json()["error"]["code"] == "INVALID_CURSOR"
    assert api.get(path).json()["regions"][0]["region_code"] == "11590"
