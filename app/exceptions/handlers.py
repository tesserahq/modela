from dataclasses import dataclass
from traceback import format_exc
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.completion_run_error import CompletionRunError
from app.exceptions.conflict_error import ConflictError
from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.exceptions.provider_errors import ProviderError, ProviderTimeoutError
from app.exceptions.resource_not_found_error import ResourceNotFoundError
from app.exceptions.structured_output_validation_error import (
    StructuredOutputValidationError,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CompletionRunError)
    async def completion_run_error_handler(request: Request, exc: CompletionRunError):
        error = _describe_completion_error(exc.original_error)
        return JSONResponse(
            status_code=error.status_code,
            content={**error.content, "extensions": {"events": exc.events}},
        )

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc)},
        )

    @app.exception_handler(InvalidParameterError)
    async def invalid_parameter_handler(request: Request, exc: InvalidParameterError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": str(exc)},
        )

    @app.exception_handler(ResourceNotFoundError)
    async def resource_not_found_handler(request: Request, exc: ResourceNotFoundError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(exc)},
        )

    @app.exception_handler(StructuredOutputValidationError)
    async def structured_output_validation_handler(
        request: Request, exc: StructuredOutputValidationError
    ):
        return _completion_error_response(exc)

    @app.exception_handler(ProviderTimeoutError)
    async def provider_timeout_handler(request: Request, exc: ProviderTimeoutError):
        return _completion_error_response(exc)

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request: Request, exc: ProviderError):
        return _completion_error_response(exc)

    @app.exception_handler(Exception)
    async def debug_exception_handler(request: Request, exc: Exception):

        tracback_msg = format_exc()
        return JSONResponse(
            {
                "code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "message": f"error info: {tracback_msg}",
                # "message": f"error info: {str(exc)}",
                "data": "",
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@dataclass(frozen=True)
class _ErrorDescription:
    """Transport-neutral description shared by wrapped and direct failures."""

    status_code: int
    content: dict[str, Any]


def _describe_completion_error(exc: Exception) -> _ErrorDescription:
    """Classify a completion failure without coupling it to an HTTP response."""
    if isinstance(exc, StructuredOutputValidationError):
        return _ErrorDescription(
            status.HTTP_502_BAD_GATEWAY,
            {
                "detail": str(exc),
                "validation_errors": exc.validation_errors,
                "raw_content": exc.raw_content,
            },
        )
    if isinstance(exc, ProviderTimeoutError):
        return _ErrorDescription(
            status.HTTP_504_GATEWAY_TIMEOUT,
            {"detail": str(exc)},
        )
    if isinstance(exc, ProviderError):
        return _ErrorDescription(
            status.HTTP_502_BAD_GATEWAY,
            {"detail": str(exc)},
        )
    return _ErrorDescription(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        {"detail": str(exc)},
    )


def _completion_error_response(exc: Exception) -> JSONResponse:
    error = _describe_completion_error(exc)
    return JSONResponse(status_code=error.status_code, content=error.content)
