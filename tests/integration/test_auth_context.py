"""认证占位与用户上下文接口测试。

当前测试目标不是验证真实 JWT 签名，
而是确保当前阶段的认证占位方案具备三项能力：
1. 本地开发可以在无认证头时回退到 mock 用户；
2. 显式传入用户头时，接口会按该用户上下文执行；
3. 非法认证头会被统一拦截并返回稳定错误结构。
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app


@pytest.fixture()
def client() -> TestClient:
    """创建测试用 FastAPI Client。"""

    return TestClient(app)


def test_chat_allows_local_mock_user_when_auth_headers_absent(client: TestClient) -> None:
    """本地开发阶段未传认证头时，应允许回退到 mock 用户。"""

    response = client.post(
        "/api/v1/chat",
        json={
            "query": "集团新能源业务有哪些核心制度？",
            "conversation_id": None,
            "history_messages": [],
            "business_hint": None,
            "knowledge_base_ids": [],
            "stream": False,
        },
    )

    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["meta"]["conversation_id"].startswith("conv_")


def test_conversations_uses_explicit_user_headers_and_writes_user_log(
    client: TestClient,
    caplog,
) -> None:
    """显式用户头应进入用户上下文，并体现在访问日志里。"""

    headers = {
        "Authorization": "Bearer local-dev-token",
        "X-User-Id": "42",
        "X-Username": "energy_analyst",
        "X-Display-Name": "Energy Analyst",
        "X-User-Roles": "employee,analyst",
        "X-User-Permissions": "chat:read,chat:write",
        "X-Department-Code": "planning-center",
    }

    chat_response = client.post(
        "/api/v1/chat",
        headers=headers,
        json={
            "query": "集团新能源业务有哪些核心制度？",
            "conversation_id": None,
            "history_messages": [],
            "business_hint": None,
            "knowledge_base_ids": [],
            "stream": False,
        },
    )
    assert chat_response.status_code == 200

    with caplog.at_level(logging.INFO, logger="apps.api.access"):
        conversations_response = client.get("/api/v1/conversations", headers=headers)

    payload = conversations_response.json()

    assert conversations_response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["total"] >= 1
    assert any(
        "user_id=42" in record.getMessage() and "username=energy_analyst" in record.getMessage()
        for record in caplog.records
    )


def test_chat_rejects_invalid_authorization_scheme(client: TestClient) -> None:
    """非法 Authorization Scheme 应返回统一 401 错误。"""

    response = client.post(
        "/api/v1/chat",
        headers={"Authorization": "Basic demo"},
        json={
            "query": "集团新能源业务有哪些核心制度？",
            "conversation_id": None,
            "history_messages": [],
            "business_hint": None,
            "knowledge_base_ids": [],
            "stream": False,
        },
    )
    payload = response.json()

    assert response.status_code == 401
    assert payload["success"] is False
    assert payload["error_code"] == "UNAUTHORIZED"
