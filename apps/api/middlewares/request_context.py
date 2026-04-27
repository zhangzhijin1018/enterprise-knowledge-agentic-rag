"""请求上下文中间件。

该中间件负责为每个 HTTP 请求注入：
- request_id：定位单次 API 请求；
- trace_id：串联后续 task run、tool call、error log 和审计日志。
- access log：记录最小请求日志，便于后端排障和链路追踪。

当前阶段先在应用内本地生成 UUID 风格标识。
后续如果接入正式的 Trace 系统或网关透传 Header，
只需要替换这里的生成/读取逻辑，而不需要修改 router 和 service。
"""

from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Request

logger = logging.getLogger("apps.api.access")


def _resolve_request_identifier(header_value: str | None, prefix: str) -> str:
    """解析或生成链路标识。

    业务意义：
    - 如果上游网关已经透传了 request_id / trace_id，应优先复用，
      这样才能把 API 网关、应用服务、后续 task run 串在同一条链路里；
    - 如果当前是本地开发或直连服务，没有上游头信息，
      再由应用生成最小可用的占位标识。
    """

    if header_value:
        normalized = header_value.strip()
        if normalized:
            return normalized
    return f"{prefix}_{uuid4().hex[:12]}"


async def attach_request_context(request: Request, call_next):
    """为请求注入 request_id、trace_id，并输出最小 access log。"""

    request.state.request_id = _resolve_request_identifier(
        request.headers.get("X-Request-ID"),
        prefix="req",
    )
    request.state.trace_id = _resolve_request_identifier(
        request.headers.get("X-Trace-ID"),
        prefix="tr",
    )
    start_time = perf_counter()

    response = await call_next(request)
    duration_ms = round((perf_counter() - start_time) * 1000, 2)

    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Trace-ID"] = request.state.trace_id

    # 当前先记录最小请求完成日志，不额外写 body、token 或敏感参数，
    # 避免在最小骨架阶段就引入日志泄密风险。
    user_context = getattr(request.state, "user_context", None)
    user_id = getattr(user_context, "user_id", None)
    username = getattr(user_context, "username", None)

    logger.info(
        "api_request_completed method=%s path=%s status_code=%s duration_ms=%s request_id=%s trace_id=%s user_id=%s username=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request.state.request_id,
        request.state.trace_id,
        user_id,
        username,
    )
    return response
