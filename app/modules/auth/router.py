from fastapi import APIRouter, Response

from app.api.dependencies import Database
from app.core.errors import API_ERRORS, ErrorResponse
from app.modules.auth import service
from app.modules.auth.dependencies import Member
from app.modules.auth.schemas import KakaoLogin, LoginResult, MyAccount, RefreshInput, TokenPair
from app.modules.seniors.withdrawal import withdraw

router = APIRouter(tags=["auth"], responses=API_ERRORS)


@router.post("/auth/kakao", responses={503: {"model": ErrorResponse}})
def login(data: KakaoLogin, session: Database, response: Response) -> LoginResult:
    response.headers["Cache-Control"] = "no-store"
    return service.login(session, data.access_token.get_secret_value())


@router.post("/auth/refresh")
def refresh(data: RefreshInput, session: Database, response: Response) -> TokenPair:
    response.headers["Cache-Control"] = "no-store"
    return service.refresh(session, data.refresh_token.get_secret_value())


@router.post("/auth/logout", status_code=204)
def logout(account: Member, data: RefreshInput, session: Database):
    service.logout(session, account, data.refresh_token.get_secret_value())
    return Response(status_code=204)


@router.get("/users/me")
def me(account: Member) -> MyAccount:
    return MyAccount(user_id=account.user_id, senior_id=account.senior_id, roles=["senior"])


@router.delete("/users/me", status_code=204, responses={503: {"model": ErrorResponse}})
def delete_account(account: Member, session: Database):
    withdraw(session, account.user_id)
    return Response(status_code=204)
