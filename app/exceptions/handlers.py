from traceback import format_exc
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from app.exceptions.conflict_error import ConflictError
from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.exceptions.resource_not_found_error import ResourceNotFoundError
from app.exceptions.provider_errors import ProviderError, ProviderTimeoutError
from app.exceptions.structured_output_validation_error import (
    StructuredOutputValidationError,
)


def register_exception_handlers(app: FastAPI) -> None:
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
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "detail": str(exc),
                "validation_errors": exc.validation_errors,
                "raw_content": exc.raw_content,
            },
        )

    @app.exception_handler(ProviderTimeoutError)
    async def provider_timeout_handler(request: Request, exc: ProviderTimeoutError):
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={"detail": str(exc)},
        )

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request: Request, exc: ProviderError):
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": str(exc)},
        )

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
