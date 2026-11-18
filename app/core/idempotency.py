import hashlib
import json

from sqlalchemy import select, text

from app.core.errors import DomainError
from app.db.models.registration import IdempotencyRecord


def fingerprint(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def lock_key(session, key):
    value = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": value})


def replay(session, owner, subject, operation, key, payload):
    if not key.strip():
        raise DomainError(422, "VALIDATION_ERROR", "멱등 키가 필요합니다.")
    lock_key(session, f"{owner}:{subject}:{operation}:{key}")
    row = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.owner_service == owner,
            IdempotencyRecord.subject_id == subject,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.key == key,
        )
    )
    if row and row.request_hash != fingerprint(payload):
        raise DomainError(409, "IDEMPOTENCY_CONFLICT", "같은 키의 요청 내용이 다릅니다.")
    return row


def remember(session, owner, subject, operation, key, payload, status, body):
    session.add(
        IdempotencyRecord(
            owner_service=owner,
            subject_id=subject,
            operation=operation,
            key=key,
            request_hash=fingerprint(payload),
            http_status=status,
            response_body=body,
        )
    )
