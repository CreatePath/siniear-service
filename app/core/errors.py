from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

ErrorCode = Literal[
    "AUTH_REQUIRED",
    "PROFILE_REQUIRED",
    "PROFILE_EXISTS",
    "PROFILE_CHANGED",
    "PHOTO_NOT_FOUND",
    "INTERVIEW_NOT_FOUND",
    "INTERVIEW_CHANGED",
    "MODEL_UNAVAILABLE",
    "CARD_NOT_FOUND",
    "CARD_CHANGED",
    "KAKAO_UNAVAILABLE",
    "FORBIDDEN",
    "GROUP_NOT_FOUND",
    "GROUP_CLOSED",
    "POST_NOT_FOUND",
    "COMMENT_NOT_FOUND",
    "MEETING_NOT_FOUND",
    "SENIOR_NOT_FOUND",
    "REGISTRATION_NOT_FOUND",
    "INVALID_CURSOR",
    "AMBIGUOUS_REGION",
    "SEARCH_REGION_REQUIRED",
    "VALIDATION_ERROR",
    "INVALID_MEETING_TIME",
    "INVALID_TIME_RANGE",
    "IDEMPOTENCY_CONFLICT",
    "REGISTRATION_CLOSED",
    "MEETING_FULL",
    "REGISTRATION_CHANGED",
    "CANCELLATION_CLOSED",
    "MEETING_FINISHED",
    "MEETING_STARTED",
    "CAPACITY_BELOW_PARTICIPANTS",
    "HTTP_ERROR",
    "INTERNAL_ERROR",
    "DATA_INTEGRITY_ERROR",
]


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


API_ERRORS = {code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 422, 500)}


class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def install_error_handlers(app: FastAPI):
    def response(status, code, message):
        request_id = str(uuid4())
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request_id,
                }
            },
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return response(422, "VALIDATION_ERROR", "입력 필드와 형식을 확인해 주세요.")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        if request.url.path == "/api/health/ready" and exc.status_code == 503:
            return JSONResponse(status_code=503, content={"detail": "Database unavailable"})
        return response(exc.status_code, "HTTP_ERROR", "요청을 처리할 수 없습니다.")

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        return response(500, "INTERNAL_ERROR", "요청 처리 중 오류가 발생했습니다.")
