import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.common.exceptions import (
    ArgumentException,
    AuthException,
    PipelineRAGBaseException,
    RateLimitException,
)

logger = structlog.get_logger(__name__)


async def pipeline_rag_exception_handler(
    request: Request, exc: PipelineRAGBaseException
) -> JSONResponse:
    logger.warning("business exception", code=exc.code, message=exc.message)
    headers = None
    if isinstance(exc, AuthException):
        status_code = 401
    elif isinstance(exc, RateLimitException):
        status_code = 429
        if exc.retry_after:
            headers = {"Retry-After": str(exc.retry_after)}
    elif isinstance(exc, ArgumentException):
        status_code = 400
    else:
        status_code = 200
    return JSONResponse(
        status_code=status_code,
        content={"code": exc.code, "message": exc.message, "data": getattr(exc, "errors", None)},
        headers=headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    logger.warning("validation error", errors=exc.errors())

    formatted_errors = []
    for err in exc.errors():
        loc = ".".join([str(x) for x in err["loc"]])
        formatted_errors.append({"argumentName": loc, "message": err["msg"]})

    return JSONResponse(
        status_code=422, content={"code": -100, "data": formatted_errors, "message": None}
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled exception", url=str(request.url), error=str(exc))
    return JSONResponse(
        status_code=500, content={"code": -100, "message": "系统错误，请稍后重试!", "data": None}
    )


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器——将业务异常、校验异常、未捕获异常统一为 JSON 响应"""
    app.add_exception_handler(PipelineRAGBaseException, pipeline_rag_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
