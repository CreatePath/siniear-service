from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models.call_runtime import OutboxMessage


def deliver_one(engine, producer, send, at=None):
    at = at or datetime.now(UTC)
    token = uuid4()
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(OutboxMessage)
            .where(
                OutboxMessage.producer_service == producer,
                OutboxMessage.state.in_(["pending", "sending"]),
                OutboxMessage.available_at <= at,
                or_(OutboxMessage.lease_until.is_(None), OutboxMessage.lease_until < at),
            )
            .order_by(OutboxMessage.available_at, OutboxMessage.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return False
        row.state, row.lease_token, row.lease_until = "sending", token, at + timedelta(seconds=60)
        row.attempts += 1
        row_id, operation, resource, key, payload = (
            row.id,
            row.operation,
            row.resource_id,
            row.dedupe_key,
            row.payload,
        )
    error = None
    try:
        send(operation, resource, key, payload)
    except Exception:
        error = "DELIVERY_FAILED"  # Do not persist raw HTTP/provider errors or phone numbers.
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(OutboxMessage).where(OutboxMessage.id == row_id).with_for_update()
        )
        if row is not None and row.lease_token == token and row.state == "sending":
            row.state = "pending" if error else "delivered"
            row.last_error = error
            row.available_at = at + timedelta(seconds=min(300, 2 ** min(row.attempts, 8)))
            row.lease_token = row.lease_until = None
    return True
