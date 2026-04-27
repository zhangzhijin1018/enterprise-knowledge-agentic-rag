"""最小后端骨架 API 集成测试。

当前阶段已经有：
- Service 层单元测试；
- SQLAlchemy 持久化集成测试；
- 认证占位解析测试；

这里补的是“接口联调闭环”这一层证据，目的不是重复测底层实现，
而是确认前端未来最先依赖的几条正式 API 能串起来工作：
1. `/api/v1/chat`
2. `/api/v1/conversations`
3. `/api/v1/conversations/{conversation_id}/messages`
4. `/api/v1/clarifications/{clarification_id}/reply`
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from core.repositories.conversation_repository import reset_in_memory_conversation_store
from core.repositories.task_run_repository import reset_in_memory_task_run_store


@pytest.fixture()
def client() -> TestClient:
    """创建测试客户端，并在每个用例前后清理内存状态。"""

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    with TestClient(app) as test_client:
        yield test_client
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()


def build_auth_headers(
    user_id: int = 7,
    username: str = "api_user",
) -> dict[str, str]:
    """构造显式用户上下文请求头。

    当前阶段仍未接真实 JWT 验签，
    但 API 层已经支持通过 Bearer 占位 + 用户头透传模拟正式调用链路。
    """

    return {
        "Authorization": "Bearer local-api-token",
        "X-User-Id": str(user_id),
        "X-Username": username,
        "X-Display-Name": username.replace("_", " ").title(),
        "X-User-Roles": "employee",
        "X-User-Permissions": "chat:read,chat:write",
        "X-Department-Code": "planning-center",
    }


def test_api_chat_conversation_and_message_flow(client: TestClient) -> None:
    """直接回答路径应能通过正式 API 串起 chat、会话列表和消息回放。"""

    headers = build_auth_headers(user_id=7, username="policy_user")

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
    chat_payload = chat_response.json()

    assert chat_response.status_code == 200
    assert chat_payload["success"] is True
    assert chat_payload["meta"]["status"] == "succeeded"
    assert chat_response.headers["X-Request-ID"].startswith("req_")
    assert chat_response.headers["X-Trace-ID"].startswith("tr_")

    conversation_id = chat_payload["meta"]["conversation_id"]

    conversations_response = client.get("/api/v1/conversations", headers=headers)
    conversations_payload = conversations_response.json()

    assert conversations_response.status_code == 200
    assert conversations_payload["data"]["total"] == 1
    assert conversations_payload["data"]["items"][0]["conversation_id"] == conversation_id

    messages_response = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
    )
    messages_payload = messages_response.json()

    assert messages_response.status_code == 200
    assert len(messages_payload["data"]["messages"]) == 2
    assert messages_payload["data"]["messages"][0]["role"] == "user"
    assert messages_payload["data"]["messages"][1]["role"] == "assistant"


def test_api_clarification_reply_flow(client: TestClient) -> None:
    """澄清路径应能通过正式 API 进入补槽并恢复执行。"""

    headers = build_auth_headers(user_id=8, username="analytics_user")

    chat_response = client.post(
        "/api/v1/chat",
        headers=headers,
        json={
            "query": "帮我分析经营情况",
            "conversation_id": None,
            "history_messages": [],
            "business_hint": None,
            "knowledge_base_ids": [],
            "stream": False,
        },
    )
    chat_payload = chat_response.json()

    assert chat_response.status_code == 200
    assert chat_payload["meta"]["status"] == "awaiting_user_clarification"

    conversation_id = chat_payload["meta"]["conversation_id"]
    clarification_id = chat_payload["data"]["clarification"]["clarification_id"]

    reply_response = client.post(
        f"/api/v1/clarifications/{clarification_id}/reply",
        headers=headers,
        json={"reply": "发电量"},
    )
    reply_payload = reply_response.json()

    assert reply_response.status_code == 200
    assert reply_payload["meta"]["status"] == "succeeded"

    messages_response = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
    )
    messages_payload = messages_response.json()

    assert messages_response.status_code == 200
    assert len(messages_payload["data"]["messages"]) == 4
    assert messages_payload["data"]["messages"][2]["message_type"] == "clarification_reply"
    assert messages_payload["data"]["messages"][3]["message_type"] == "answer"


def test_api_rejects_cross_user_message_access(client: TestClient) -> None:
    """跨用户读取会话消息应在 API 层返回统一 403 错误结构。"""

    owner_headers = build_auth_headers(user_id=9, username="owner_user")
    other_headers = build_auth_headers(user_id=10, username="other_user")

    chat_response = client.post(
        "/api/v1/chat",
        headers=owner_headers,
        json={
            "query": "集团新能源业务有哪些核心制度？",
            "conversation_id": None,
            "history_messages": [],
            "business_hint": None,
            "knowledge_base_ids": [],
            "stream": False,
        },
    )
    conversation_id = chat_response.json()["meta"]["conversation_id"]

    forbidden_response = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=other_headers,
    )
    forbidden_payload = forbidden_response.json()

    assert forbidden_response.status_code == 403
    assert forbidden_payload["success"] is False
    assert forbidden_payload["error_code"] == "PERMISSION_DENIED"
