import json
import re
from http.client import HTTPException, HTTPSConnection

from app.core.config import get_settings
from app.core.errors import DomainError


def unavailable():
    return DomainError(503, "KAKAO_UNAVAILABLE", "카카오 요청을 잠시 후 다시 시도해 주세요.")


def invalid_token():
    return DomainError(401, "AUTH_REQUIRED", "카카오 로그인을 다시 진행해 주세요.")


def verify_access_token(token: str) -> int:
    app_id = get_settings().kakao_app_id
    if not app_id:
        raise unavailable()
    if not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token):
        raise invalid_token()
    connection = HTTPSConnection("kapi.kakao.com", timeout=5)
    try:
        connection.request(
            "GET", "/v1/user/access_token_info", headers={"Authorization": f"Bearer {token}"}
        )
        response = connection.getresponse()
        if response.status == 401:
            raise invalid_token()
        if response.status != 200:
            raise unavailable()
        info = json.loads(response.read(16384))
    except (OSError, HTTPException, ValueError):
        raise unavailable() from None
    finally:
        connection.close()
    if not isinstance(info, dict) or any(
        type(info.get(field)) is not int for field in ("id", "app_id", "expires_in")
    ):
        raise unavailable()
    if info["app_id"] != app_id or info["expires_in"] <= 0 or not 0 < info["id"] < 2**63:
        raise invalid_token()
    return info["id"]


def unlink(kakao_id: int):
    key = get_settings().kakao_admin_key.get_secret_value()
    if not key:
        raise unavailable()
    connection = HTTPSConnection("kapi.kakao.com", timeout=5)
    try:
        connection.request(
            "POST",
            "/v1/user/unlink",
            body=f"target_id_type=user_id&target_id={kakao_id}",
            headers={
                "Authorization": f"KakaoAK {key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        response = connection.getresponse()
        body = json.loads(response.read(16384))
    except (OSError, HTTPException, ValueError):
        raise unavailable() from None
    finally:
        connection.close()
    if isinstance(body, dict):
        if response.status == 200 and type(body.get("id")) is int and body["id"] == kakao_id:
            return
        if response.status == 400 and body.get("code") == -101:
            return  # Already unlinked, including after an earlier response was lost.
    raise unavailable()
