"""经营分析 Workflow Adapter 测试。"""

from __future__ import annotations

import pytest

from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.agent.workflows.analytics import (
    AnalyticsWorkflowAdapter,
    AnalyticsWorkflowOutcome,
    AnalyticsWorkflowStage,
)
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.common.cache import reset_global_cache
from core.config.settings import Settings
from core.repositories.analytics_result_repository import reset_in_memory_analytics_result_store
from core.repositories.conversation_repository import ConversationRepository, reset_in_memory_conversation_store
from core.repositories.data_source_repository import reset_in_memory_data_source_store
from core.repositories.sql_audit_repository import SQLAuditRepository, reset_in_memory_sql_audit_store
from core.repositories.task_run_repository import TaskRunRepository, reset_in_memory_task_run_store
from core.security.auth import UserContext
from core.services.analytics_service import AnalyticsService
from core.tools.a2a import TaskEnvelope
from core.tools.sql.sql_gateway import SQLGateway


@pytest.fixture(autouse=True)
def reset_state() -> None:
    """重置内存状态，避免不同测试之间互相污染。"""

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


def build_user_context(user_id: int = 1961) -> UserContext:
    """构造最小用户上下文。"""

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


def build_analytics_service() -> AnalyticsService:
    """构造最小 AnalyticsService。"""

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
        sql_builder=SQLBuilder(
            schema_registry=schema_registry,
            metric_catalog=metric_catalog,
        ),
        sql_guard=SQLGuard(allowed_tables=["analytics_metrics_daily"]),
        sql_gateway=SQLGateway(schema_registry=schema_registry),
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )


def test_analytics_workflow_adapter_happy_path() -> None:
    """Adapter 应能通过 workflow 跑通最小成功链路。"""

    adapter = AnalyticsWorkflowAdapter(build_analytics_service())

    result = adapter.execute_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    assert result["meta"]["status"] == "succeeded"
    assert result["data"]["summary"]
    assert result["data"]["chart_spec"] is not None
    assert result["data"]["insight_cards"]


def test_analytics_workflow_adapter_returns_clarification_when_slots_missing() -> None:
    """缺少关键槽位时，Adapter 应返回结构化 clarification。"""

    adapter = AnalyticsWorkflowAdapter(build_analytics_service())

    result = adapter.execute_query(
        query="帮我分析一下上个月的情况",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    assert result["meta"]["status"] == "awaiting_user_clarification"
    assert result["data"]["clarification"]["clarification_type"] == "missing_required_slot"
    assert result["data"]["clarification"]["target_slots"] == ["metric"]


def test_analytics_workflow_adapter_maps_workflow_state_to_result_contract() -> None:
    """Adapter 应把微观 workflow state 稳定收敛成宏观 ResultContract。"""

    adapter = AnalyticsWorkflowAdapter(build_analytics_service())
    workflow_state = adapter.execute_state(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
        run_id="run_adapter_001",
        trace_id="trace_adapter_001",
        parent_task_id="parent_adapter_001",
    )
    envelope = TaskEnvelope(
        run_id="run_adapter_001",
        trace_id="trace_adapter_001",
        parent_task_id="parent_adapter_001",
        task_type="business_analysis",
        source_agent="supervisor",
        target_agent="analytics",
        input_payload={
            "query": "帮我分析一下上个月新疆区域发电量",
            "user_context": build_user_context(),
            "output_mode": "lite",
        },
    )

    result_contract = adapter.to_result_contract(
        envelope=envelope,
        response=workflow_state["final_response"],
        workflow_state=workflow_state,
    )

    assert workflow_state["workflow_stage"] == AnalyticsWorkflowStage.ANALYTICS_FINISH
    assert workflow_state["workflow_outcome"] == AnalyticsWorkflowOutcome.FINISH
    assert result_contract.status.status == "succeeded"
    assert result_contract.run_id == "run_adapter_001"
    assert result_contract.trace_id == "trace_adapter_001"
    assert result_contract.output_payload["meta"]["status"] == "succeeded"
