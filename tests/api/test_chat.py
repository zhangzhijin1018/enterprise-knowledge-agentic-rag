"""Chat API 最小闭环测试。"""

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


def build_auth_headers(user_id: int = 101, username: str = "chat_api_user") -> dict[str, str]:
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


def test_chat_answer_branch(client: TestClient) -> None:
    """普通问答应走直接回答分支。"""

    response = client.post(
        "/api/v1/chat",
        headers=build_auth_headers(),
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
    assert payload["meta"]["status"] == "succeeded"
    assert "answer" in payload["data"]


def test_chat_clarification_branch(client: TestClient) -> None:
    """经营分析缺指标时应进入澄清分支。"""

    response = client.post(
        "/api/v1/chat",
        headers=build_auth_headers(user_id=102, username="analytics_api_user"),
        json={
            "query": "帮我分析经营情况",
            "conversation_id": None,
            "history_messages": [],
            "business_hint": None,
            "knowledge_base_ids": [],
            "stream": False,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["meta"]["status"] == "awaiting_user_clarification"
    assert payload["meta"]["need_clarification"] is True
    assert payload["data"]["clarification"]["target_slots"] == ["metric"]
