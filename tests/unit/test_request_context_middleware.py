"""请求上下文中间件测试。

当前测试目标不是验证完整审计系统，
而是确保 API 最小入口层已经具备两项基础能力：
1. 每个请求都有稳定的 request_id / trace_id；
2. 请求完成后会输出最小 access log，便于后续排障和链路串联。
"""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from apps.api.main import app


def test_health_response_contains_generated_request_headers() -> None:
    """未传入链路头时，中间件应自动生成 request_id 和 trace_id。"""

    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")
    assert response.headers["X-Trace-ID"].startswith("tr_")


def test_health_request_preserves_incoming_headers_and_writes_access_log(caplog) -> None:
    """如果上游已透传链路标识，中间件应保留原值并写入请求完成日志。"""

    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="apps.api.access"):
        response = client.get(
            "/health",
            headers={
                "X-Request-ID": "req_from_gateway",
                "X-Trace-ID": "tr_from_gateway",
            },
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req_from_gateway"
    assert response.headers["X-Trace-ID"] == "tr_from_gateway"
    assert any(
        "api_request_completed" in record.getMessage()
        and "request_id=req_from_gateway" in record.getMessage()
        and "trace_id=tr_from_gateway" in record.getMessage()
        for record in caplog.records
    )
