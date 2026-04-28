"""经营分析 API 测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from core.repositories.conversation_repository import reset_in_memory_conversation_store
from core.repositories.sql_audit_repository import reset_in_memory_sql_audit_store
from core.repositories.task_run_repository import reset_in_memory_task_run_store


@pytest.fixture()
def client() -> TestClient:
    """创建 API 测试客户端。"""

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    with TestClient(app) as test_client:
        yield test_client
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()


def build_auth_headers(user_id: int = 1301, username: str = "analytics_api_user") -> dict[str, str]:
    """构造最小测试认证头。"""

    return {
        "Authorization": "Bearer local-api-token",
        "X-User-Id": str(user_id),
        "X-Username": username,
        "X-Display-Name": username,
        "X-User-Roles": "employee",
        "X-User-Permissions": "analytics:query",
        "X-Department-Code": "analytics-center",
    }


def test_analytics_query_returns_summary_and_tables_when_slots_are_complete(client: TestClient) -> None:
    """槽位齐全时应直接执行并返回 summary + tables。"""

    response = client.post(
        "/api/v1/analytics/query",
        headers=build_auth_headers(),
        json={
            "query": "帮我分析一下上个月新疆区域发电量",
            "conversation_id": None,
            "output_mode": "summary",
            "need_sql_explain": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["meta"]["status"] == "succeeded"
    assert payload["data"]["summary"]
    assert payload["data"]["tables"]
    assert payload["meta"]["run_id"]
    assert payload["data"]["sql_preview"] is not None
    assert payload["data"]["safety_check_result"]["is_safe"] is True
    assert payload["data"]["metric_scope"] == "发电量"
    assert payload["data"]["data_source"] == "local_analytics"
    assert payload["data"]["row_count"] is not None
    assert payload["data"]["latency_ms"] is not None


def test_analytics_query_returns_clarification_when_metric_missing(client: TestClient) -> None:
    """缺少 metric 时应进入澄清分支。"""

    response = client.post(
        "/api/v1/analytics/query",
        headers=build_auth_headers(user_id=1302, username="analytics_clarification_user"),
        json={
            "query": "帮我分析一下上个月的情况",
            "conversation_id": None,
            "output_mode": "summary",
            "need_sql_explain": False,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["meta"]["status"] == "awaiting_user_clarification"
    assert payload["data"]["clarification"]["target_slots"] == ["metric"]


def test_analytics_run_detail_returns_latest_sql_audit(client: TestClient) -> None:
    """运行详情应包含最近一次 SQL 审计信息。"""

    submit_response = client.post(
        "/api/v1/analytics/query",
        headers=build_auth_headers(user_id=1303, username="analytics_run_user"),
        json={
            "query": "帮我分析一下上个月新疆区域发电量",
            "conversation_id": None,
            "output_mode": "summary",
            "need_sql_explain": False,
        },
    )
    run_id = submit_response.json()["meta"]["run_id"]

    detail_response = client.get(
        f"/api/v1/analytics/runs/{run_id}",
        headers=build_auth_headers(user_id=1303, username="analytics_run_user"),
    )
    payload = detail_response.json()

    assert detail_response.status_code == 200
    assert payload["data"]["latest_sql_audit"] is not None
    assert payload["data"]["latest_sql_audit"]["execution_status"] == "succeeded"
