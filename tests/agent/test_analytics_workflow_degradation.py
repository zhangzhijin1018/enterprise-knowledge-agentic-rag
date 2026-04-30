"""经营分析 workflow 降级策略测试。"""

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


def build_user_context(user_id: int = 2801) -> UserContext:
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


def test_chart_insight_and_report_failures_can_degrade_without_blocking_query() -> None:
    """洞察/图表/报告失败时，应降级返回，不阻断主查询成功。"""

    service = build_service()
    adapter = AnalyticsWorkflowAdapter(service)
    service._build_chart_spec = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("chart failed"))  # type: ignore[method-assign]
    service.insight_builder.build = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("insight failed"))  # type: ignore[method-assign]
    service.report_formatter.build = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("report failed"))  # type: ignore[method-assign]

    result = adapter.execute_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    assert result["meta"]["status"] == "succeeded"
    assert result["meta"]["degraded"] is True
    assert set(result["meta"]["degraded_features"]) == {"chart_spec", "insight_cards", "report_blocks"}
    assert result["data"]["summary"]
    assert result["data"]["tables"]
    assert result["data"]["chart_spec"] is None
    assert result["data"]["insight_cards"] == []
    assert result["data"]["report_blocks"] == []
    assert set(result["data"]["degraded_features"]) == {"chart_spec", "insight_cards", "report_blocks"}


def test_sql_execution_failure_cannot_fake_successful_result() -> None:
    """SQL 执行失败时不能伪造 summary/table 成功结果。"""

    service = build_service()
    adapter = AnalyticsWorkflowAdapter(service)

    def always_fail(*args, **kwargs):
        raise SQLGatewayExecutionError("network down", error_code="sql_gateway_timeout")

    service.sql_gateway.execute_readonly_query = always_fail  # type: ignore[method-assign]

    with pytest.raises(AppException, match="经营分析 SQL 执行失败"):
        adapter.execute_query(
            query="帮我分析一下上个月新疆区域发电量",
            conversation_id=None,
            output_mode="full",
            need_sql_explain=False,
            user_context=build_user_context(user_id=2802),
        )
