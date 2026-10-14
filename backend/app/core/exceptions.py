"""Shared API error envelope; raw exception details are never sent to clients."""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.core.config import DatabaseNotConfiguredError
from app.schemas.common import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self, code: str, message: str, status_code: int = 400, details: dict[str, int | str | list[str]] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def error_response(
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
    details: dict[str, int | str | list[str]] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=payload.model_dump(exclude_none=True), headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, details=exc.details)

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        try:
            status = HTTPStatus(exc.status_code)
            code, message = status.name, status.phrase
        except ValueError:
            code, message = "HTTP_ERROR", "HTTP request failed"
        return error_response(exc.status_code, code, message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "VALIDATION_ERROR", "Request validation failed")

    @app.exception_handler(DatabaseNotConfiguredError)
    async def handle_database_configuration(request: Request, exc: Exception) -> JSONResponse:
        return error_response(503, "DATABASE_NOT_CONFIGURED", "Database is not configured")

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Exception messages may contain passwords, SQL parameters or provider tokens.
        logger.error("Unhandled application exception (%s)", type(exc).__name__)
        return error_response(500, "INTERNAL_SERVER_ERROR", "Internal server error")
