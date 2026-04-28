"""AnalyticsService 测试。"""

from __future__ import annotations

import pytest

from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.common.exceptions import AppException
from core.repositories.conversation_repository import ConversationRepository, reset_in_memory_conversation_store
from core.repositories.sql_audit_repository import SQLAuditRepository, reset_in_memory_sql_audit_store
from core.repositories.task_run_repository import TaskRunRepository, reset_in_memory_task_run_store
from core.security.auth import UserContext
from core.services.analytics_service import AnalyticsService
from core.tools.local.sql_executor import LocalSQLExecutor


@pytest.fixture(autouse=True)
def reset_state() -> None:
    """重置内存状态。"""

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    yield
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()


def build_user_context(user_id: int = 1201) -> UserContext:
    """构造最小用户上下文。"""

    return UserContext(
        user_id=user_id,
        username=f"user_{user_id}",
        display_name=f"user_{user_id}",
        roles=["employee"],
        department_code="analytics-center",
        permissions=["analytics:query"],
    )


def build_service() -> AnalyticsService:
    """构造最小 AnalyticsService。"""

    return AnalyticsService(
        conversation_repository=ConversationRepository(session=None),
        task_run_repository=TaskRunRepository(session=None),
        sql_audit_repository=SQLAuditRepository(session=None),
        analytics_planner=AnalyticsPlanner(),
        sql_builder=SQLBuilder(),
        sql_guard=SQLGuard(allowed_tables=["analytics_metrics_daily"]),
        sql_executor=LocalSQLExecutor(),
    )


def test_analytics_service_runs_successfully_when_metric_and_time_range_are_present() -> None:
    """metric + time_range 齐全时应进入执行链路并成功返回摘要。"""

    service = build_service()

    result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="summary",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    assert result["meta"]["status"] == "succeeded"
    assert "summary" in result["data"]
    assert result["data"]["tables"]


def test_analytics_service_returns_clarification_when_metric_missing() -> None:
    """缺少 metric 时应返回澄清。"""

    service = build_service()

    result = service.submit_query(
        query="帮我分析一下上个月的情况",
        conversation_id=None,
        output_mode="summary",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    assert result["meta"]["status"] == "awaiting_user_clarification"
    assert result["data"]["clarification"]["target_slots"] == ["metric"]


def test_analytics_service_blocks_query_without_time_range() -> None:
    """缺少 time_range 时也必须澄清，不能直接执行 SQL。"""

    service = build_service()

    result = service.submit_query(
        query="帮我分析一下新疆区域发电量",
        conversation_id=None,
        output_mode="summary",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    assert result["meta"]["status"] == "awaiting_user_clarification"
    assert result["data"]["clarification"]["target_slots"] == ["time_range"]


def test_analytics_service_get_run_detail_contains_sql_audit() -> None:
    """成功执行后，运行详情应能看到最新 SQL 审计。"""

    service = build_service()

    submit_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="summary",
        need_sql_explain=True,
        user_context=build_user_context(),
    )
    run_id = submit_result["meta"]["run_id"]

    detail_result = service.get_run_detail(
        run_id=run_id,
        user_context=build_user_context(),
    )

    assert detail_result["data"]["latest_sql_audit"] is not None
    assert detail_result["data"]["latest_sql_audit"]["is_safe"] is True


def test_analytics_service_raises_for_unauthorized_run_detail() -> None:
    """不同用户不应查看他人的经营分析运行详情。"""

    service = build_service()

    submit_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="summary",
        need_sql_explain=False,
        user_context=build_user_context(user_id=1201),
    )

    with pytest.raises(AppException):
        service.get_run_detail(
            run_id=submit_result["meta"]["run_id"],
            user_context=build_user_context(user_id=1202),
        )
