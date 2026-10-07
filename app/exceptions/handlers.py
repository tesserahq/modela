from collections.abc import Callable
from dataclasses import dataclass
from traceback import format_exception
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.completion_run_error import CompletionRunError
from app.exceptions.conflict_error import ConflictError
from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.exceptions.provider_errors import ProviderError, ProviderTimeoutError
from app.exceptions.resource_not_found_error import ResourceNotFoundError
from app.exceptions.structured_output_validation_error import (
    StructuredOutputValidationError,
)
from app.infra.logging_config import get_logger

logger = get_logger()


@dataclass(frozen=True)
class _ErrorDescription:
    """Transport-neutral description shared by wrapped and direct failures."""

    status_code: int
    content: dict[str, Any]
    headers: dict[str, str] | None = None


_Describer = Callable[[Any], _ErrorDescription]
_DESCRIBERS: dict[type[Exception], _Describer] = {}


def _describes(exc_type: type[Exception]) -> Callable[[_Describer], _Describer]:
    def register(describer: _Describer) -> _Describer:
        _DESCRIBERS[exc_type] = describer
        return describer

    return register


@_describes(ConflictError)
def _conflict(exc: ConflictError) -> _ErrorDescription:
    return _ErrorDescription(status.HTTP_409_CONFLICT, {"detail": str(exc)})


@_describes(InvalidParameterError)
def _invalid_parameter(exc: InvalidParameterError) -> _ErrorDescription:
    return _ErrorDescription(
        status.HTTP_422_UNPROCESSABLE_CONTENT, {"detail": str(exc)}
    )


@_describes(ResourceNotFoundError)
def _resource_not_found(exc: ResourceNotFoundError) -> _ErrorDescription:
    return _ErrorDescription(status.HTTP_404_NOT_FOUND, {"detail": str(exc)})


@_describes(StructuredOutputValidationError)
def _structured_output_validation(
    exc: StructuredOutputValidationError,
) -> _ErrorDescription:
    return _ErrorDescription(
        status.HTTP_502_BAD_GATEWAY,
        {
            "detail": str(exc),
            "validation_errors": exc.validation_errors,
            "raw_content": exc.raw_content,
        },
    )


@_describes(ProviderTimeoutError)
def _provider_timeout(exc: ProviderTimeoutError) -> _ErrorDescription:
    return _ErrorDescription(status.HTTP_504_GATEWAY_TIMEOUT, {"detail": str(exc)})


@_describes(ProviderError)
def _provider_error(exc: ProviderError) -> _ErrorDescription:
    return _ErrorDescription(status.HTTP_502_BAD_GATEWAY, {"detail": str(exc)})


# Mirrors FastAPI's default HTTPException response so a wrapped HTTPException
# keeps its status; the direct path stays on FastAPI's own handler.
@_describes(HTTPException)
def _http_exception(exc: HTTPException) -> _ErrorDescription:
    return _ErrorDescription(exc.status_code, {"detail": exc.detail}, exc.headers)


def _describe_error(exc: Exception) -> _ErrorDescription | None:
    """Classify a known error by its most specific registered type."""
    for exc_type in type(exc).__mro__:
        describer = _DESCRIBERS.get(exc_type)
        if describer is not None:
            return describer(exc)
    return None


def _internal_error(exc: Exception) -> _ErrorDescription:
    return _ErrorDescription(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        {
            "code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "message": f"error info: {''.join(format_exception(exc))}",
            "data": "",
        },
    )


def _response(
    error: _ErrorDescription, extra: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={**error.content, **(extra or {})},
        headers=error.headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CompletionRunError)
    async def completion_run_error_handler(request: Request, exc: CompletionRunError):
        original = exc.original_error
        error = _describe_error(original)
        if error is None:
            # Handled here, so ServerErrorMiddleware never re-raises it: log it
            # the way an unwrapped unexpected error would be.
            logger.error("Unhandled error during completion", exc_info=original)
            error = _internal_error(original)
        extensions = {"events": exc.events}
        if exc.truncations:
            extensions["truncations"] = exc.truncations
        return _response(error, {"extensions": extensions})

    async def known_error_handler(request: Request, exc: Exception):
        return _response(_describe_error(exc))

    for exc_type in _DESCRIBERS:
        if exc_type is not HTTPException:
            app.add_exception_handler(exc_type, known_error_handler)

    @app.exception_handler(Exception)
    async def debug_exception_handler(request: Request, exc: Exception):
        return _response(_internal_error(exc))
