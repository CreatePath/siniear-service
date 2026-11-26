from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from google.auth.credentials import AnonymousCredentials
from requests.exceptions import Timeout

from app.integrations import fcm


@pytest.fixture
def sender(monkeypatch):
    monkeypatch.setattr(fcm.google.auth, "default", lambda **_: (AnonymousCredentials(), None))
    sender = fcm.FcmSender("test-project")
    sender.http = Mock()
    return sender


def award():
    return SimpleNamespace(id=uuid4(), label="새로운 얼굴", tier="silver", membership_id=uuid4())


@pytest.mark.parametrize("tier", ["silver", "gold", "diamond"])
def test_os_notification_and_stable_award_id(sender, tier):
    sender.http.post.return_value.status_code = 200
    sender.http.post.return_value.json.return_value = {"name": "projects/test/messages/accepted"}
    title = award()
    title.tier = tier
    sender.send("synthetic", title)
    args, kwargs = sender.http.post.call_args
    assert args == ("https://fcm.googleapis.com/v1/projects/test-project/messages:send",)
    msg = kwargs["json"]["message"]
    assert msg["token"] == "synthetic"
    assert title.label in msg["notification"]["body"]
    assert (
        msg["android"]["notification"]["tag"]
        == msg["apns"]["headers"]["apns-collapse-id"]
        == str(title.id)
    )
    assert msg["data"] == {
        "type": "title_awarded",
        "label": title.label,
        "tier": tier,
        "title_id": str(title.id),
        "membership_id": str(title.membership_id),
    }


@pytest.mark.parametrize(
    "status,code,error",
    [
        (404, "UNREGISTERED", fcm.UnregisteredToken),
        (404, "NOT_FOUND", fcm.RetryPush),
        (429, "QUOTA_EXCEEDED", fcm.RetryPush),
        (503, "UNAVAILABLE", fcm.RetryPush),
        (400, "INVALID_ARGUMENT", fcm.PushRejected),
    ],
)
def test_provider_errors(sender, status, code, error):
    response = sender.http.post.return_value
    response.status_code = status
    response.headers = {"Retry-After": "120"}
    response.json.return_value = {
        "error": {
            "details": [
                {"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": code}
            ]
        }
    }
    with pytest.raises(error) as exc:
        sender.send("synthetic", award())
    if error == fcm.RetryPush:
        assert exc.value.delay == 120


def test_timeout_is_retryable(sender):
    sender.http.post.side_effect = Timeout()
    with pytest.raises(fcm.RetryPush):
        sender.send("synthetic", award())


@pytest.mark.parametrize("status,body", [(200, {}), (404, {"error": {"details": None}}), (404, [])])
def test_unrecognized_provider_response_is_retryable(sender, status, body):
    response = sender.http.post.return_value
    response.status_code = status
    response.headers = {}
    response.json.return_value = body
    with pytest.raises(fcm.RetryPush):
        sender.send("synthetic", award())
