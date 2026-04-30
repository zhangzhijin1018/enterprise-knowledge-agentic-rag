"""Supervisor 宏观状态机测试。"""

from __future__ import annotations

import pytest

from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.agent.supervisor import DelegationController, SupervisorService
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
from core.tools.a2a import AgentCardRef, DelegationTarget
from core.tools.sql.sql_gateway import SQLGateway
from core.agent.workflows.analytics import AnalyticsWorkflowAdapter


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


def build_user_context(user_id: int = 1991) -> UserContext:
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


def test_supervisor_status_machine_reports_succeeded_for_local_workflow() -> None:
    """本地 workflow happy path 应映射成 succeeded。"""

    adapter = AnalyticsWorkflowAdapter(build_analytics_service())
    supervisor = SupervisorService(
        delegation_controller=DelegationController(
            local_handlers={"analytics_expert": adapter.as_local_handler()},
        )
    )

    result = supervisor.handle_request(
        task_type="business_analysis",
        input_payload={
            "query": "帮我分析一下上个月新疆区域发电量",
            "conversation_id": None,
            "output_mode": "lite",
            "need_sql_explain": False,
            "user_context": build_user_context(),
        },
    )

    assert result.status.status == "succeeded"
    assert result.status.sub_status == "collecting_result"


def test_supervisor_status_machine_reports_waiting_remote() -> None:
    """远程占位委托应映射成 waiting_remote。"""

    remote_target = DelegationTarget(
        task_type="business_analysis",
        route_key="analytics",
        agent_card=AgentCardRef(
            agent_name="analytics_expert_remote",
            description="远程经营分析专家",
            capabilities=["business_analysis"],
            execution_mode="a2a_ready",
        ),
        preferred_transport="http_json",
    )
    supervisor = SupervisorService(
        delegation_controller=DelegationController(
            delegation_targets={"business_analysis": remote_target},
        )
    )

    result = supervisor.handle_request(
        task_type="business_analysis",
        input_payload={
            "query": "帮我分析一下上个月新疆区域发电量",
            "conversation_id": None,
            "output_mode": "lite",
            "need_sql_explain": False,
            "user_context": build_user_context(),
        },
    )

    assert result.status.status == "waiting_remote"
    assert result.status.sub_status == "awaiting_remote_result"


def test_supervisor_status_machine_reports_failed_when_local_handler_missing() -> None:
    """本地 handler 缺失时，应映射成 failed。"""

    supervisor = SupervisorService(
        delegation_controller=DelegationController(local_handlers={}),
    )

    result = supervisor.handle_request(
        task_type="business_analysis",
        input_payload={
            "query": "帮我分析一下上个月新疆区域发电量",
            "conversation_id": None,
            "output_mode": "lite",
            "need_sql_explain": False,
            "user_context": build_user_context(),
        },
    )

    assert result.status.status == "failed"
    assert result.status.sub_status == "terminal_failure"
