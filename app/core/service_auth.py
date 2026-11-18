import secrets
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.errors import DomainError

bearer = HTTPBearer(auto_error=False)


def require_service(scope):
    def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        settings = get_settings()
        secret = settings.internal_inbound_token.get_secret_value()
        if (
            not secret
            or credentials is None
            or not secrets.compare_digest(credentials.credentials, secret)
        ):
            raise DomainError(401, "AUTH_REQUIRED", "서비스 인증이 필요합니다.")
        if scope not in settings.internal_scopes.split():
            raise DomainError(403, "FORBIDDEN", "서비스 권한이 없습니다.")
        return settings.internal_peer

    return authenticate
