"""经营分析 clarification API 测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from core.common.async_task_runner import reset_async_task_runner
from core.common.cache import reset_global_cache
from core.repositories.analytics_result_repository import reset_in_memory_analytics_result_store
from core.repositories.conversation_repository import reset_in_memory_conversation_store
from core.repositories.data_source_repository import reset_in_memory_data_source_store
from core.repositories.sql_audit_repository import reset_in_memory_sql_audit_store
from core.repositories.task_run_repository import reset_in_memory_task_run_store


@pytest.fixture()
def client() -> TestClient:
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_data_source_store()
    reset_in_memory_analytics_result_store()
    reset_async_task_runner()
    reset_global_cache()
    with TestClient(app) as test_client:
        yield test_client
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_data_source_store()
    reset_in_memory_analytics_result_store()
    reset_async_task_runner()
    reset_global_cache()


def build_auth_headers(user_id: int = 2901, username: str = "analytics_clar_user") -> dict[str, str]:
    return {
        "Authorization": "Bearer local-api-token",
        "X-User-Id": str(user_id),
        "X-Username": username,
        "X-Display-Name": username,
        "X-User-Roles": "employee,analyst",
        "X-User-Permissions": "analytics:query,analytics:metric:generation,analytics:metric:revenue,analytics:metric:cost,analytics:metric:profit,analytics:metric:output",
        "X-Department-Code": "analytics-center",
    }


def test_analytics_clarification_reply_can_resume_via_api(client: TestClient) -> None:
    """经营分析澄清回复接口应能复用原 run_id 恢复执行。"""

    headers = build_auth_headers()
    first_response = client.post(
        "/api/v1/analytics/query",
        headers=headers,
        json={
            "query": "帮我分析一下上个月的情况",
            "conversation_id": None,
            "output_mode": "standard",
            "need_sql_explain": False,
        },
    )
    first_payload = first_response.json()
    clarification_id = first_payload["data"]["clarification"]["clarification_id"]
    run_id = first_payload["meta"]["run_id"]

    reply_response = client.post(
        f"/api/v1/analytics/clarifications/{clarification_id}/reply",
        headers=headers,
        json={
            "reply": "发电量",
            "output_mode": "standard",
            "need_sql_explain": False,
        },
    )
    reply_payload = reply_response.json()

    assert reply_response.status_code == 200
    assert reply_payload["meta"]["status"] == "succeeded"
    assert reply_payload["meta"]["run_id"] == run_id
    assert reply_payload["data"]["summary"]


def test_analytics_clarification_detail_can_be_read(client: TestClient) -> None:
    """经营分析澄清详情接口应返回结构化事件信息。"""

    headers = build_auth_headers(user_id=2902, username="analytics_clar_user_2")
    first_response = client.post(
        "/api/v1/analytics/query",
        headers=headers,
        json={
            "query": "帮我分析一下上个月的情况",
            "conversation_id": None,
            "output_mode": "lite",
            "need_sql_explain": False,
        },
    )
    clarification_id = first_response.json()["data"]["clarification"]["clarification_id"]

    detail_response = client.get(
        f"/api/v1/analytics/clarifications/{clarification_id}",
        headers=headers,
    )
    detail_payload = detail_response.json()

    assert detail_response.status_code == 200
    assert detail_payload["data"]["clarification_id"] == clarification_id
    assert detail_payload["data"]["status"] == "pending"
    assert detail_payload["data"]["target_slots"] == ["metric"]
