"""经营分析 workflow 重试策略测试。"""

from __future__ import annotations

import pytest

from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.agent.workflows.analytics import AnalyticsWorkflowAdapter
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.common.cache import reset_global_cache
from core.common.exceptions import AppException
from core.config.settings import Settings
from core.repositories.analytics_result_repository import reset_in_memory_analytics_result_store
from core.repositories.conversation_repository import ConversationRepository, reset_in_memory_conversation_store
from core.repositories.data_source_repository import reset_in_memory_data_source_store
from core.repositories.sql_audit_repository import SQLAuditRepository, reset_in_memory_sql_audit_store
from core.repositories.task_run_repository import TaskRunRepository, reset_in_memory_task_run_store
from core.security.auth import UserContext
from core.services.analytics_service import AnalyticsService
from core.tools.mcp import SQLGatewayExecutionError
from core.tools.sql.sql_gateway import SQLGateway


@pytest.fixture(autouse=True)
def reset_state() -> None:
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_data_source_store()
    reset_in_memory_analytics_result_store()
    reset_global_cache()
    yield
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_data_source_store()
    reset_in_memory_analytics_result_store()
    reset_global_cache()


def build_user_context(user_id: int = 2701) -> UserContext:
    return UserContext(
        user_id=user_id,
        username=f"user_{user_id}",
        display_name=f"user_{user_id}",
        roles=["employee", "analyst"],
        department_code="analytics-center",
        permissions=[
            "analytics:query",
            "analytics:metric:generation",
            "analytics:metric:revenue",
            "analytics:metric:cost",
            "analytics:metric:profit",
            "analytics:metric:output",
        ],
    )


def build_service() -> AnalyticsService:
    schema_registry = SchemaRegistry()
    metric_catalog = MetricCatalog(
        default_data_source=schema_registry.get_default_data_source().key,
        default_table_name=schema_registry.get_default_data_source().default_table,
    )
    return AnalyticsService(
        conversation_repository=ConversationRepository(session=None),
        task_run_repository=TaskRunRepository(session=None),
        sql_audit_repository=SQLAuditRepository(session=None),
        analytics_planner=AnalyticsPlanner(
            metric_catalog=metric_catalog,
            llm_planner_gateway=LLMAnalyticsPlannerGateway(settings=Settings()),
        ),
        sql_builder=SQLBuilder(schema_registry=schema_registry, metric_catalog=metric_catalog),
        sql_guard=SQLGuard(allowed_tables=["analytics_metrics_daily"]),
        sql_gateway=SQLGateway(schema_registry=schema_registry),
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )


def test_sql_gateway_temporary_error_can_retry_and_recover() -> None:
    """SQL Gateway 临时失败后，应允许有限重试并最终成功。"""

    service = build_service()
    adapter = AnalyticsWorkflowAdapter(service)
    original_execute = service.sql_gateway.execute_readonly_query
    attempts = {"count": 0}

    def flaky_execute(request):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise SQLGatewayExecutionError("temporary timeout", error_code="sql_gateway_timeout")
        return original_execute(request)

    service.sql_gateway.execute_readonly_query = flaky_execute  # type: ignore[method-assign]

    state = adapter.execute_state(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    assert attempts["count"] == 2
    assert state["retry_count"] == 1
    assert state["retry_history"][0]["node_name"] == "analytics_execute_sql"
    assert state["final_response"]["meta"]["status"] == "succeeded"


def test_sql_guard_blocked_should_not_retry() -> None:
    """SQL Guard blocked 属于治理拒绝，不允许通过重试绕过。"""

    service = build_service()
    adapter = AnalyticsWorkflowAdapter(service)
    attempts = {"count": 0}

    class _UnsafeResult:
        is_safe = False
        checked_sql = None
        blocked_reason = "guard blocked"
        governance_detail = {}

    def blocked_validate(*args, **kwargs):
        attempts["count"] += 1
        return _UnsafeResult()

    service.sql_guard.validate = blocked_validate  # type: ignore[method-assign]

    with pytest.raises(AppException, match="SQL 安全检查未通过"):
        adapter.execute_state(
            query="帮我分析一下上个月新疆区域发电量",
            conversation_id=None,
            output_mode="lite",
            need_sql_explain=False,
            user_context=build_user_context(user_id=2702),
        )

    assert attempts["count"] == 1
