import json
from types import SimpleNamespace

import pytest

from app.core.errors import DomainError
from app.integrations import kakao


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (200, {"app_id": 42, "id": 123, "expires_in": 15}, None),
        (200, {"app_id": 41, "id": 123, "expires_in": 15}, 401),
        (200, {"app_id": 42, "id": 123, "expires_in": 0}, 401),
        (200, {"app_id": 42, "id": True, "expires_in": 15}, 503),
        (200, [], 503),
        (200, None, 503),
        (401, {}, 401),
        (429, {}, 503),
        (500, {}, 503),
    ],
)
def test_token_info(monkeypatch, status, body, error):
    class FakeConnection:
        def __init__(self, host, timeout):
            assert host == "kapi.kakao.com" and timeout > 0

        def request(self, method, path, headers):
            assert (method, path) == ("GET", "/v1/user/access_token_info")
            assert headers == {"Authorization": "Bearer synthetic"}

        def getresponse(self):
            return SimpleNamespace(
                status=status,
                read=lambda limit: json.dumps(body).encode() if body is not None else b"bad json",
            )

        def close(self):
            pass

    monkeypatch.setattr(kakao, "get_settings", lambda: SimpleNamespace(kakao_app_id=42))
    monkeypatch.setattr(kakao, "HTTPSConnection", FakeConnection)
    if error:
        with pytest.raises(DomainError) as exc:
            kakao.verify_access_token("synthetic")
        assert exc.value.status == error
    else:
        assert kakao.verify_access_token("synthetic") == 123


@pytest.mark.parametrize(
    "status,body,success",
    [
        (200, {"id": 123}, True),
        (400, {"code": -101}, True),
        (200, {"id": 124}, False),
        (401, {}, False),
        (503, {}, False),
    ],
)
def test_unlink(monkeypatch, status, body, success):
    from pydantic import SecretStr

    class FakeConnection:
        def request(self, method, path, body, headers):
            assert (method, path) == ("POST", "/v1/user/unlink")
            assert body == "target_id_type=user_id&target_id=123"
            assert headers["Authorization"] == "KakaoAK synthetic"

        def getresponse(self):
            return SimpleNamespace(status=status, read=lambda limit: json.dumps(body).encode())

        def close(self):
            pass

    monkeypatch.setattr(
        kakao, "get_settings", lambda: SimpleNamespace(kakao_admin_key=SecretStr("synthetic"))
    )
    monkeypatch.setattr(kakao, "HTTPSConnection", lambda host, timeout: FakeConnection())
    if success:
        kakao.unlink(123)
    else:
        with pytest.raises(DomainError) as exc:
            kakao.unlink(123)
        assert exc.value.status == 503
