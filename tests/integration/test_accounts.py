from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import User
from app.db.models.identity import RefreshSession
from app.integrations import kakao
from tests.integration.test_groups_meetings import create_group, meeting_data

PROFILE = {
    "name": "가상 회원",
    "region_code": "TEST",
    "interests": ["산책"],
}


def bearer(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def sign_in(api, monkeypatch):
    def verify(token):
        if token == "invalid":
            raise kakao.invalid_token()
        return {"sample-a": 101, "sample-b": 102}[token]

    monkeypatch.setattr(kakao, "verify_access_token", verify)
    monkeypatch.setattr(kakao, "unlink", lambda kakao_id: None)

    def login(token="sample-a"):
        response = api.post("/api/auth/kakao", json={"access_token": token})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        return response.json()

    return login


def test_login_rotation_and_device_logout(api, db_engine, sign_in, monkeypatch):
    monkeypatch.setenv("DEV_AUTH_ENABLED", "false")
    get_settings.cache_clear()
    assert api.post("/api/auth/kakao", json={"access_token": "invalid"}).status_code == 401
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(RefreshSession)) == 0
        assert session.scalar(select(User.id).where(User.kakao_user_id.is_not(None))) is None
    with ThreadPoolExecutor(2) as pool:
        first, second = list(pool.map(sign_in, ["sample-a"] * 2))
    assert first["user_id"] == second["user_id"]
    actor = bearer(first["access_token"])
    assert api.get("/api/users/me", headers=actor).json()["senior_id"] is None
    assert api.get("/api/groups", headers=actor).json()["error"]["code"] == "PROFILE_REQUIRED"
    assert api.get("/api/groups").status_code == 401
    path = "/api/auth/refresh"
    body = {"refresh_token": first["refresh_token"]}
    assert api.get("/api/users/me", headers=bearer(first["refresh_token"])).status_code == 401
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: api.post(path, json=body), range(2)))
    assert sorted(r.status_code for r in results) == [200, 401]
    rotated = next(r.json() for r in results if r.status_code == 200)
    assert api.get("/api/users/me", headers=actor).status_code == 401
    actor = bearer(rotated["access_token"])
    assert (
        api.post(
            "/api/auth/logout", headers=actor, json={"refresh_token": second["refresh_token"]}
        ).status_code
        == 401
    )
    assert (
        api.post(
            "/api/auth/logout", headers=actor, json={"refresh_token": rotated["refresh_token"]}
        ).status_code
        == 204
    )
    assert api.get("/api/users/me", headers=actor).status_code == 401
    assert api.post(path, json={"refresh_token": rotated["refresh_token"]}).status_code == 401
    assert api.get("/api/users/me", headers=bearer(second["access_token"])).status_code == 200


def test_member_onboarding_and_ownership(api, sign_in):
    login = sign_in()
    actor = bearer(login["access_token"])
    assert api.get("/api/users/me", headers=bearer("dev:" + login["user_id"])).status_code == 401
    with ThreadPoolExecutor(2) as pool:
        responses = list(
            pool.map(lambda _: api.post("/api/seniors", headers=actor, json=PROFILE), range(2))
        )
    assert sorted(r.status_code for r in responses) == [201, 409]
    senior = next(r.json() for r in responses if r.status_code == 201)
    assert senior["version"] == 1
    assert "phone_number" not in senior and "call_agree" not in senior
    assert api.get("/api/users/me", headers=actor).json()["senior_id"] == senior["id"]
    path = "/api/seniors/" + senior["id"]
    assert api.get(path, headers=actor).json() == senior
    assert api.get(path).status_code == 403
    assert api.patch(path, headers={"If-Match": '"1"'}, json={"intro": "합성"}).status_code == 403
    assert api.patch(path, headers=actor, json={}).status_code == 422
    edit_headers = {**actor, "If-Match": '"1"'}
    assert api.patch(path, headers=edit_headers, json={"region_code": "B"}).json()["version"] == 2
    assert api.patch(path, headers=edit_headers, json={"name": "합성"}).status_code == 409
    assert api.get("/api/groups", headers=actor).status_code == 200


def test_expired_sessions_and_withdrawal_before_profile(api, db_engine, sign_in):
    old = sign_in()
    with Session(db_engine) as session, session.begin():
        row = session.scalar(select(RefreshSession))
        assert old["access_token"] != row.access_hash and old["refresh_token"] != row.refresh_hash
        row.access_expires_at = row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert api.get("/api/users/me", headers=bearer(old["access_token"])).status_code == 401
    assert (
        api.post("/api/auth/refresh", json={"refresh_token": old["refresh_token"]}).status_code
        == 401
    )
    current = sign_in()
    assert api.delete("/api/users/me", headers=bearer(current["access_token"])).status_code == 204
    assert api.get("/api/users/me", headers=bearer(current["access_token"])).status_code == 401
    assert sign_in()["user_id"] != old["user_id"]


def test_unlink_failure_rolls_back_and_retry_only_erases_owner(api, sign_in, monkeypatch):
    owner = sign_in()
    other = sign_in("sample-b")
    actor = bearer(owner["access_token"])
    other_actor = bearer(other["access_token"])
    api.headers.update(actor)
    assert api.post("/api/seniors", json=PROFILE).status_code == 201
    assert api.post("/api/seniors", json=PROFILE, headers=other_actor).status_code == 201
    group = create_group(api)
    payload = meeting_data()
    del payload["region_code"]
    meeting = api.post(f"/api/groups/{group['id']}/meetings", json=payload).json()
    path = f"/api/meetings/{meeting['id']}"
    assert (
        api.post(
            path + "/registrations", headers={**other_actor, "Idempotency-Key": "join"}
        ).status_code
        == 201
    )

    def fail(kakao_id):
        assert kakao_id == 101
        raise kakao.unavailable()

    monkeypatch.setattr(kakao, "unlink", fail)
    assert api.delete("/api/users/me").status_code == 503
    assert api.get(path).json()["participant_count"] == 1
    unlinked = []
    monkeypatch.setattr(kakao, "unlink", unlinked.append)
    assert api.delete("/api/users/me").status_code == 204
    assert unlinked == [101]
    assert api.get(path).status_code == 401
    assert api.get(path, headers=other_actor).json()["status"] == "canceled"
    assert api.get(f"/api/groups/{group['id']}", headers=other_actor).json()["status"] == "closed"
