"""经营分析导出 API 测试。"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from core.common.async_task_runner import reset_async_task_runner
from core.common.cache import reset_global_cache
from core.repositories.analytics_export_repository import reset_in_memory_analytics_export_store
from core.repositories.analytics_review_repository import reset_in_memory_analytics_review_store
from core.repositories.analytics_result_repository import reset_in_memory_analytics_result_store
from core.repositories.conversation_repository import reset_in_memory_conversation_store
from core.repositories.data_source_repository import reset_in_memory_data_source_store
from core.repositories.sql_audit_repository import reset_in_memory_sql_audit_store
from core.repositories.task_run_repository import reset_in_memory_task_run_store


@pytest.fixture()
def client() -> TestClient:
    """创建 API 测试客户端。"""

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_analytics_export_store()
    reset_in_memory_analytics_review_store()
    reset_in_memory_data_source_store()
    reset_in_memory_analytics_result_store()
    reset_async_task_runner()
    reset_global_cache()
    with TestClient(app) as test_client:
        yield test_client
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_analytics_export_store()
    reset_in_memory_analytics_review_store()
    reset_in_memory_data_source_store()
    reset_in_memory_analytics_result_store()
    reset_async_task_runner()
    reset_global_cache()


def build_auth_headers(user_id: int = 1501, username: str = "analytics_export_user") -> dict[str, str]:
    """构造最小测试认证头。"""

    return {
        "Authorization": "Bearer local-api-token",
        "X-User-Id": str(user_id),
        "X-Username": username,
        "X-Display-Name": username,
        "X-User-Roles": "employee,analyst",
        "X-User-Permissions": "analytics:query,analytics:metric:generation,analytics:metric:revenue,analytics:metric:cost,analytics:metric:profit,analytics:metric:output",
        "X-Department-Code": "analytics-center",
    }


def wait_for_export_status(
    client: TestClient,
    *,
    export_id: str,
    headers: dict[str, str],
    timeout_seconds: float = 2.0,
) -> dict:
    """轮询等待导出任务到达终态。"""

    deadline = time.time() + timeout_seconds
    last_payload: dict | None = None
    while time.time() < deadline:
        response = client.get(
            f"/api/v1/analytics/exports/{export_id}",
            headers=headers,
        )
        last_payload = response.json()
        if last_payload["data"]["status"] in {"succeeded", "failed"}:
            return last_payload
        time.sleep(0.05)
    assert last_payload is not None
    return last_payload


def test_analytics_export_can_be_created_and_read(client: TestClient) -> None:
    """基于已存在的 analytics run 应能创建并读取 export。"""

    analytics_response = client.post(
        "/api/v1/analytics/query",
        headers=build_auth_headers(),
        json={
            "query": "帮我分析一下上个月新疆区域发电量",
            "conversation_id": None,
            "output_mode": "full",
            "need_sql_explain": True,
        },
    )
    run_id = analytics_response.json()["meta"]["run_id"]

    export_response = client.post(
        f"/api/v1/analytics/runs/{run_id}/export",
        headers=build_auth_headers(),
        json={"export_type": "markdown", "export_template": "monthly_report"},
    )
    export_payload = export_response.json()
    export_id = export_payload["data"]["export_id"]

    assert export_response.status_code == 200
    assert export_payload["meta"]["status"] == "pending"
    assert export_payload["data"]["run_id"] == run_id
    assert export_payload["data"]["export_template"] == "monthly_report"
    detail_payload = wait_for_export_status(
        client,
        export_id=export_id,
        headers=build_auth_headers(),
    )
    assert detail_payload["data"]["export_id"] == export_id
    assert detail_payload["data"]["status"] == "succeeded"
    assert detail_payload["data"]["export_template"] == "monthly_report"
    assert detail_payload["data"]["filename"].endswith(".md")
    assert detail_payload["data"]["governance_decision"]["effective_filters"]["department_code"] == "analytics-center"
