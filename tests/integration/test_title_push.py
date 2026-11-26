import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Event
from unittest.mock import Mock
from uuid import UUID

from google.auth.credentials import AnonymousCredentials
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.identity import RefreshSession
from app.db.models.membership import MembershipTitle
from app.db.models.push import PushDevice, TitlePushDelivery
from app.integrations import fcm
from app.integrations.fcm import RetryPush, UnregisteredToken
from app.modules.auth.service import rotate
from app.modules.groups.activity_titles import award_titles
from app.workers.title_push import deliver_one
from scripts.seed_dev import ids
from tests.integration.conftest import auth
from tests.integration.test_groups_meetings import create_group

PATH = "/api/me/push-token"


def login(db_engine, account):
    now = datetime.now(UTC)
    with Session(db_engine) as db, db.begin():
        row = RefreshSession(user_id=ids(account)[0], expires_at=now + timedelta(days=1))
        pair = rotate(row, now)
        db.add(row)
        db.flush()
        return {"Authorization": f"Bearer {pair.access_token}"}, pair.refresh_token, row.id


def bind(api, headers, token):
    response = api.put(PATH, headers=headers, json={"token": token})
    assert response.status_code == 204, response.text
    assert not response.content


def send_one(db_engine, sender):
    with Session(db_engine) as db:
        return deliver_one(db, sender)


def test_award_is_atomic_private_and_delivered_per_device(api, db_engine):
    first, _, _ = login(db_engine, "owner")
    second, _, _ = login(db_engine, "owner")
    other, _, _ = login(db_engine, "member")
    assert api.put(PATH, json={"token": "mock"}).status_code == 401
    assert api.put(PATH, headers=first, json={"token": "a b"}).status_code == 422
    assert (
        api.put(
            PATH, headers=first, json={"token": "mock", "user_id": str(ids("member")[0])}
        ).status_code
        == 422
    )
    bind(api, first, "first")
    bind(api, first, "first")
    bind(api, second, "second")
    bind(api, other, "third")
    group = create_group(api)
    (m,) = api.get("/api/me/memberships").json()["items"]
    mid = UUID(m["id"])
    with Session(db_engine) as db:
        with db.begin():
            award_titles(db, mid, "join", 1, mid)
        award_titles(db, mid, "post", 10, mid)
        db.rollback()
        assert not db.scalar(select(MembershipTitle.id).where(MembershipTitle.label == "이야기꾼"))
    sender = Mock()
    seen = []
    sender.send.side_effect = lambda token, title: seen.append((token, title.label))
    while send_one(db_engine, sender):
        pass
    assert sorted(seen) == [("first", "신규 회원"), ("second", "신규 회원")]
    # One re-tried approval issues one notification for the applicant, even though the owner acts.
    path = f"/api/groups/{group['id']}/join-requests"
    req = api.post(path, headers={**auth("member"), "Idempotency-Key": "join"}).json()
    for _ in range(2):
        assert api.patch(path + "/" + req["id"], json={"status": "approved"}).status_code == 200
    assert send_one(db_engine, sender)
    assert seen[-1] == ("third", "신규 회원")
    assert not send_one(db_engine, sender)


def test_rotation_switch_logout_and_withdrawal_remove_old_deliveries(api, db_engine):
    first, refresh, _ = login(db_engine, "owner")
    second, _, _ = login(db_engine, "member")
    bind(api, first, "old")
    create_group(api)
    bind(api, first, "rotated")
    sender = Mock()
    assert send_one(db_engine, sender)
    assert sender.send.call_args.args[0] == "rotated"
    create_group(api)
    bind(api, second, "rotated")
    assert not send_one(db_engine, sender)
    bind(api, first, "fresh")
    create_group(api)
    assert (
        api.post("/api/auth/logout", headers=first, json={"refresh_token": refresh}).status_code
        == 204
    )
    assert not send_one(db_engine, sender)
    assert api.delete("/api/users/me", headers=second).status_code == 204
    with Session(db_engine) as db:
        assert not db.scalar(select(PushDevice.session_id))


def test_retry_unregistered_and_disabled_device(api, db_engine):
    headers, _, sid = login(db_engine, "owner")
    create_group(api)
    bind(api, headers, "test-device")
    sender = Mock()
    assert not send_one(db_engine, sender)  # No retroactive push.
    create_group(api)
    sender.send.side_effect = RetryPush(180)
    assert send_one(db_engine, sender)
    assert not send_one(db_engine, sender)
    with Session(db_engine) as db, db.begin():
        job = db.scalars(select(TitlePushDelivery)).one()
        assert job.attempts == 1 and job.next_attempt_at > datetime.now(UTC) + timedelta(
            seconds=170
        )
        job.next_attempt_at = datetime.now(UTC)
    sender.send.side_effect = UnregisteredToken()
    assert send_one(db_engine, sender)
    with Session(db_engine) as db:
        assert db.get(PushDevice, sid) is None
    bind(api, headers, "again")
    create_group(api)
    assert api.delete(PATH, headers=headers).status_code == 204
    assert not send_one(db_engine, sender)


def test_concurrent_worker_skips_inflight_job(api, db_engine):
    headers, _, _ = login(db_engine, "owner")
    bind(api, headers, "concurrent")
    create_group(api)
    entered, finish = Event(), Event()

    def sending(token, title):
        entered.set()
        assert finish.wait(5)

    sender = Mock()
    sender.send.side_effect = sending
    with ThreadPoolExecutor(1) as pool:
        sent = pool.submit(send_one, db_engine, sender)
        try:
            assert entered.wait(5)
            assert not send_one(db_engine, sender)
        finally:
            finish.set()
        assert sent.result()
    sender.send.assert_called_once()
    with Session(db_engine) as db:
        assert db.scalar(select(func.count()).select_from(TitlePushDelivery)) == 0


def test_worker_submits_os_notification_over_http(api, db_engine, monkeypatch):
    headers, _, _ = login(db_engine, "owner")
    bind(api, headers, "wire-test")
    create_group(api)
    received = []

    class Endpoint(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"name":"projects/test/messages/1"}')

        def log_message(self, *args):
            pass

    monkeypatch.setattr(fcm.google.auth, "default", lambda **_: (AnonymousCredentials(), None))
    sender = fcm.FcmSender("test")
    with HTTPServer(("127.0.0.1", 0), Endpoint) as endpoint, ThreadPoolExecutor(1) as pool:
        endpoint.timeout = 5
        processing = pool.submit(endpoint.handle_request)
        sender.url = f"http://127.0.0.1:{endpoint.server_port}/v1/projects/test/messages:send"
        assert send_one(db_engine, sender)
        processing.result(timeout=6)
    message = received[0]["message"]
    assert message["token"] == "wire-test"
    assert message["data"]["type"] == "title_awarded"
    assert "신규 회원" in message["notification"]["body"]
    assert not send_one(db_engine, sender)


def test_closed_membership_and_expired_login_skip_send(api, db_engine):
    headers, _, sid = login(db_engine, "owner")
    bind(api, headers, "expires")
    group = create_group(api)
    assert api.patch(f"/api/groups/{group['id']}", json={"status": "closed"}).status_code == 200
    sender = Mock()
    assert send_one(db_engine, sender)
    create_group(api)
    with Session(db_engine) as db, db.begin():
        db.get(RefreshSession, sid).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert send_one(db_engine, sender)
    sender.send.assert_not_called()
