"""Supervisor 与经营分析 workflow 真实接入测试。"""

from __future__ import annotations

import pytest

from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.agent.supervisor import DelegationController, SupervisorService
from core.agent.workflows.analytics import AnalyticsWorkflowAdapter
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
from core.tools.sql.sql_gateway import SQLGateway


@pytest.fixture(autouse=True)
def reset_state() -> None:
    """重置内存状态。"""

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


def build_user_context(user_id: int = 1971) -> UserContext:
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


def test_supervisor_delegates_to_local_analytics_workflow_adapter() -> None:
    """Supervisor 应能通过 Adapter 调起本地 analytics workflow。"""

    adapter = AnalyticsWorkflowAdapter(build_analytics_service())
    controller = DelegationController(
        local_handlers={"analytics_expert": adapter.as_local_handler()},
    )
    supervisor = SupervisorService(delegation_controller=controller)
    user_context = build_user_context()

    result = supervisor.handle_request(
        task_type="business_analysis",
        input_payload=controller.build_input_payload(
            query="帮我分析一下上个月新疆区域发电量",
            user_context=user_context,
            output_mode="lite",
        ),
    )

    assert result.status.status == "succeeded"
    assert result.output_payload["data"]["summary"]

    events = supervisor.event_bus.consume(stream="supervisor.tasks", max_count=10)
    assert len(events) == 2
    assert events[0].event_type == "task_submitted"
    assert events[1].event_type == "task_finished"
    assert result.run_id == events[0].run_id == events[1].run_id
    assert result.trace_id == events[0].trace_id == events[1].trace_id
    assert result.output_payload["meta"]["run_id"] == result.run_id


def test_result_contract_keeps_clarification_payload_compatible() -> None:
    """缺槽位时，Supervisor 返回的 ResultContract 仍应兼容 analytics clarification 结构。"""

    adapter = AnalyticsWorkflowAdapter(build_analytics_service())
    controller = DelegationController(
        local_handlers={"analytics_expert": adapter.as_local_handler()},
    )
    supervisor = SupervisorService(delegation_controller=controller)

    result = supervisor.handle_request(
        task_type="business_analysis",
        input_payload=controller.build_input_payload(
            query="帮我分析一下上个月的情况",
            user_context=build_user_context(),
            output_mode="lite",
        ),
    )

    assert result.status.status == "awaiting_user_clarification"
    assert result.output_payload["data"]["clarification"]["target_slots"] == ["metric"]
