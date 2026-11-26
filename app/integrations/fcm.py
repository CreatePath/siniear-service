from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import google.auth
import requests
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession


class UnregisteredToken(Exception):
    pass


class PushRejected(Exception):
    """Permanent payload failure."""


class RetryPush(Exception):
    def __init__(self, delay=0):
        self.delay = delay


def retry_delay(header):
    if not header:
        return 0
    if header.isdecimal():
        return min(int(header), 86400)
    try:
        return max(
            0, min(86400, int((parsedate_to_datetime(header) - datetime.now(UTC)).total_seconds()))
        )
    except (TypeError, ValueError, OverflowError):
        return 0


class FcmSender:
    def __init__(self, project_id):
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/firebase.messaging"]
        )
        self.http = AuthorizedSession(credentials, refresh_timeout=10)
        self.url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    def send(self, token, title):
        award_id = str(title.id)
        message = {
            "token": token,
            "notification": {
                "title": "새 칭호를 받았어요",
                "body": f"‘{title.label}’ 칭호를 획득했어요.",
            },
            "data": {
                "type": "title_awarded",
                "title_id": award_id,
                "label": title.label,
                "tier": title.tier,
                "membership_id": str(title.membership_id),
            },
            "android": {"priority": "high", "notification": {"tag": award_id}},
            "apns": {"headers": {"apns-collapse-id": award_id, "apns-push-type": "alert"}},
        }
        try:
            response = self.http.post(self.url, json={"message": message}, timeout=10)
        except (requests.RequestException, GoogleAuthError):
            raise RetryPush() from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 200:
            if isinstance(body, dict) and body.get("name"):
                return
            raise RetryPush()
        if response.status_code == 404:
            error = body.get("error") if isinstance(body, dict) else None
            details = error.get("details") if isinstance(error, dict) else None
            if isinstance(details, list) and any(
                isinstance(d, dict)
                and d.get("@type") == "type.googleapis.com/google.firebase.fcm.v1.FcmError"
                and d.get("errorCode") == "UNREGISTERED"
                for d in details
            ):
                raise UnregisteredToken()
        if response.status_code == 400:
            raise PushRejected()
        # Credentials, quotas, project configuration and provider outages may recover.
        raise RetryPush(retry_delay(response.headers.get("Retry-After")))
