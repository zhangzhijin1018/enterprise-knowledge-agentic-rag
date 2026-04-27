"""Clarifications API 最小测试。"""

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


def build_auth_headers(user_id: int = 301, username: str = "clarification_api_user") -> dict[str, str]:
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


def test_clarification_reply_updates_status(client: TestClient) -> None:
    """回复澄清后应恢复执行并把状态切回 succeeded。"""

    headers = build_auth_headers()

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
    assert reply_payload["meta"]["sub_status"] == "resumed_after_clarification"

    messages_response = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
    )
    messages_payload = messages_response.json()

    assert messages_response.status_code == 200
    assert len(messages_payload["data"]["messages"]) == 4
    assert messages_payload["data"]["messages"][2]["message_type"] == "clarification_reply"
    assert messages_payload["data"]["messages"][3]["message_type"] == "answer"
