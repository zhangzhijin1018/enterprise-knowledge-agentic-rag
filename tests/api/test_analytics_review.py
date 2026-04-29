"""经营分析 Human Review API 测试。"""

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
    reset_in_memory_analytics_result_store()
    reset_in_memory_data_source_store()
    reset_async_task_runner()
    reset_global_cache()
    with TestClient(app) as test_client:
        yield test_client
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_analytics_export_store()
    reset_in_memory_analytics_review_store()
    reset_in_memory_analytics_result_store()
    reset_in_memory_data_source_store()
    reset_async_task_runner()
    reset_global_cache()


def build_auth_headers(
    user_id: int,
    username: str,
    *,
    permissions: str,
    roles: str,
) -> dict[str, str]:
    """构造测试认证头。"""

    return {
        "Authorization": "Bearer local-api-token",
        "X-User-Id": str(user_id),
        "X-Username": username,
        "X-Display-Name": username,
        "X-User-Roles": roles,
        "X-User-Permissions": permissions,
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


def test_high_risk_export_review_approve_flow(client: TestClient) -> None:
    """高风险导出应触发 review，审批通过后继续导出。"""

    owner_headers = build_auth_headers(
        1701,
        "analytics_review_owner",
        permissions="analytics:query,analytics:metric:generation,analytics:metric:revenue,analytics:metric:cost,analytics:metric:profit,analytics:metric:output",
        roles="employee,analyst",
    )
    reviewer_headers = build_auth_headers(
        2701,
        "analytics_reviewer",
        permissions="analytics:query,analytics:review,analytics:metric:generation,analytics:metric:revenue,analytics:metric:cost,analytics:metric:profit,analytics:metric:output",
        roles="manager,analyst",
    )

    analytics_response = client.post(
        "/api/v1/analytics/query",
        headers=owner_headers,
        json={
            "query": "帮我分析一下上个月新疆区域收入",
            "conversation_id": None,
            "output_mode": "full",
            "need_sql_explain": False,
        },
    )
    run_id = analytics_response.json()["meta"]["run_id"]

    export_response = client.post(
        f"/api/v1/analytics/runs/{run_id}/export",
        headers=owner_headers,
        json={"export_type": "pdf"},
    )
    export_payload = export_response.json()
    review_id = export_payload["data"]["review_id"]

    review_detail_response = client.get(
        f"/api/v1/analytics/reviews/{review_id}",
        headers=reviewer_headers,
    )
    approve_response = client.post(
        f"/api/v1/analytics/reviews/{review_id}/approve",
        headers=reviewer_headers,
        json={"comment": "审批通过，可以生成正式导出。"},
    )

    assert export_response.status_code == 200
    assert export_payload["meta"]["status"] == "awaiting_human_review"
    assert export_payload["data"]["review_status"] == "pending"
    assert review_detail_response.status_code == 200
    assert approve_response.status_code == 200
    assert approve_response.json()["data"]["review"]["review_status"] == "approved"
    assert approve_response.json()["data"]["export"]["status"] in {"pending", "running"}
    export_detail = wait_for_export_status(
        client,
        export_id=export_payload["data"]["export_id"],
        headers=owner_headers,
    )
    assert export_detail["data"]["status"] == "succeeded"
