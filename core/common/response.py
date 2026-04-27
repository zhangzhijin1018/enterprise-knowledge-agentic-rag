"""统一响应构造工具。

这里不直接依赖具体业务模块，而是提供最小复用能力：
- 统一成功响应结构；
- 统一错误响应结构；
- 统一从 Request 中读取 request_id / trace_id。
"""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from fastapi import Request


def _get_request_id(request: Request | None) -> str:
    """安全读取 request_id。

    如果当前代码路径不在 HTTP 请求上下文内，也返回一个兜底值，
    避免响应结构缺少关键链路标识。
    """

    if request is not None and hasattr(request.state, "request_id"):
        return request.state.request_id
    return f"req_{uuid4().hex[:12]}"


def _get_trace_id(request: Request | None) -> str:
    """安全读取 trace_id。"""

    if request is not None and hasattr(request.state, "trace_id"):
        return request.state.trace_id
    return f"tr_{uuid4().hex[:12]}"


def build_response_meta(**kwargs: Any) -> dict[str, Any]:
    """构造精简后的 meta。

    只保留有值字段，避免返回大量 `null` 噪音，
    让前端更容易聚焦真正有意义的状态字段。
    """

    return {key: value for key, value in kwargs.items() if value is not None}


def build_success_response(
    request: Request | None,
    data: Mapping[str, Any] | None = None,
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一成功响应。"""

    return {
        "success": True,
        "trace_id": _get_trace_id(request),
        "request_id": _get_request_id(request),
        "data": dict(data or {}),
        "meta": dict(meta or {}),
    }


def build_error_response(
    request: Request | None,
    error_code: str,
    message: str,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一错误响应。"""

    return {
        "success": False,
        "trace_id": _get_trace_id(request),
        "request_id": _get_request_id(request),
        "error_code": error_code,
        "message": message,
        "detail": dict(detail or {}),
    }
