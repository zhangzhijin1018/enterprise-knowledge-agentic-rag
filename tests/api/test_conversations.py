"""Conversations API 最小测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from core.repositories.conversation_repository import reset_in_memory_conversation_store
from core.repositories.task_run_repository import reset_in_memory_task_run_store


@pytest.fixture()
def client() -> TestClient:
    """创建 API 测试客户端，并清理内存状态。"""

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    with TestClient(app) as test_client:
        yield test_client
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()


def build_auth_headers(user_id: int = 201, username: str = "conversation_api_user") -> dict[str, str]:
    """构造最小测试认证头。"""

    return {
        "Authorization": "Bearer local-api-token",
        "X-User-Id": str(user_id),
        "X-Username": username,
        "X-Display-Name": username,
        "X-User-Roles": "employee",
        "X-User-Permissions": "chat:read,chat:write",
        "X-Department-Code": "planning-center",
    }


def _create_answer_conversation(client: TestClient, headers: dict[str, str]) -> str:
    """通过 chat 接口创建一个最小会话。"""

    response = client.post(
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
    return response.json()["meta"]["conversation_id"]


def test_list_conversations_and_messages(client: TestClient) -> None:
    """会话列表和消息列表应能正常查询。"""

    headers = build_auth_headers()
    conversation_id = _create_answer_conversation(client, headers)

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


def test_cancel_conversation(client: TestClient) -> None:
    """取消会话接口应把会话状态切换为 cancelled。"""

    headers = build_auth_headers(user_id=202, username="cancel_api_user")
    conversation_id = _create_answer_conversation(client, headers)

    cancel_response = client.post(
        f"/api/v1/conversations/{conversation_id}/cancel",
        headers=headers,
    )
    cancel_payload = cancel_response.json()

    assert cancel_response.status_code == 200
    assert cancel_payload["data"]["message"] == "会话已取消"
    assert cancel_payload["meta"]["conversation_id"] == conversation_id
    assert cancel_payload["meta"]["status"] == "cancelled"

    conversations_response = client.get(
        "/api/v1/conversations",
        headers=headers,
        params={"status": "cancelled"},
    )
    conversations_payload = conversations_response.json()

    assert conversations_response.status_code == 200
    assert conversations_payload["data"]["total"] == 1
    assert conversations_payload["data"]["items"][0]["current_status"] == "cancelled"
