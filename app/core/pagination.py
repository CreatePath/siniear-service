import base64
import hashlib
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import tuple_

from app.core.errors import DomainError


def paginate(
    session, query, *, column, id_column, limit, cursor, scope, descending=False, value_for_row=None
):
    scope_hash = hashlib.sha256(json.dumps(scope, sort_keys=True, default=str).encode()).hexdigest()
    if cursor:
        try:
            if len(cursor) > 2048:
                raise ValueError
            data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
            if data["scope"] != scope_hash:
                raise ValueError
            row_id = UUID(data["id"])
            if column.type.python_type is datetime:
                value = datetime.fromisoformat(data["value"])
                if value.utcoffset() is None:
                    raise ValueError
            else:
                value = UUID(data["value"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            raise DomainError(
                422, "INVALID_CURSOR", "현재 조회 조건의 커서를 사용해 주세요."
            ) from None
        position = tuple_(column, id_column)
        query = query.where(
            position < (value, row_id) if descending else position > (value, row_id)
        )
    order = (column.desc(), id_column.desc()) if descending else (column.asc(), id_column.asc())
    rows = session.scalars(query.order_by(*order).limit(limit + 1)).all()
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        value = value_for_row(last) if value_for_row else getattr(last, column.key)
        next_cursor = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "scope": scope_hash,
                    "id": str(last.id),
                    "value": value.isoformat() if isinstance(value, datetime) else str(value),
                }
            ).encode()
        ).decode()
    return rows[:limit], next_cursor
