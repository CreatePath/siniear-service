import json
from urllib.request import Request, urlopen

from app.core.config import get_settings


def send(operation, resource_id, key, payload):
    paths = {
        "call.start": "/api/internal/calls",
        "emergency.start": "/api/internal/emergency-calls",
    }
    settings = get_settings()
    token = settings.internal_outbound_token.get_secret_value()
    if not token:
        raise RuntimeError("Service token is not configured")
    request = Request(
        settings.peer_base_url.rstrip("/") + paths[operation],
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": key,
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=15) as response:
        body = json.load(response)
        field = "call_id" if operation == "call.start" else "delivery_id"
        if (
            response.status != 202
            or body.get(field) != str(resource_id)
            or body.get("execution_status") != "accepted"
        ):
            raise RuntimeError("Invalid execution acknowledgement")
