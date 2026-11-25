from typing import Annotated

from fastapi import Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.session import get_session
from app.modules.auth.dependencies import Principal, get_principal

Database = Annotated[Session, Depends(get_session)]
Actor = Annotated[Principal, Depends(get_principal)]

Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=2048)]


async def empty_request(request: Request):
    if await request.body():
        raise DomainError(422, "VALIDATION_ERROR", "본문을 비워 주세요.")
