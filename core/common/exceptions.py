"""统一异常定义与注册。

当前阶段先实现最小异常体系：
- AppException：业务异常基类；
- FastAPI 统一异常处理注册；
- 请求参数校验错误转换；
- 未捕获异常兜底。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from core.common import error_codes
from core.common.response import build_error_response


class AppException(Exception):
    """统一业务异常。

    业务作用：
    - 让 Service / Repository 可以抛出稳定错误；
    - 避免 router 中写大量 try / except；
    - 为后续错误码治理和审计打基础。
    """

    def __init__(
        self,
        error_code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """处理业务异常。"""

    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_response(
            request=request,
            error_code=exc.error_code,
            message=exc.message,
            detail=exc.detail,
        ),
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """把 FastAPI 校验错误统一包装成项目错误结构。"""

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=build_error_response(
            request=request,
            error_code=error_codes.REQUEST_VALIDATION_ERROR,
            message="请求参数校验失败",
            detail={"errors": exc.errors()},
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底处理未捕获异常。"""

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=build_error_response(
            request=request,
            error_code=error_codes.INTERNAL_SERVER_ERROR,
            message="系统内部错误",
            detail={"exception_type": exc.__class__.__name__},
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """向 FastAPI 应用注册统一异常处理。"""

    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
