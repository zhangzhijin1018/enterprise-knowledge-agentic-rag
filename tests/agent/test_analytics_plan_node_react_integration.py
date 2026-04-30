"""analytics_plan 节点局部 ReAct 接入测试。"""

from __future__ import annotations

import pytest

from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.agent.workflows.analytics import AnalyticsLangGraphWorkflow
from core.agent.workflows.analytics.react.planner import AnalyticsReactPlanner
from core.agent.workflows.analytics.react.policy import AnalyticsReactPlanningPolicy
from core.agent.workflows.analytics.react.tools import AnalyticsReactToolRegistry
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.common.cache import reset_global_cache
from core.config.settings import Settings
from core.llm import MockLLMGateway
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
    """重置内存仓储。"""

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


def _user_context() -> UserContext:
    """构造经营分析测试用户。"""

    return UserContext(
        user_id=8801,
        username="analytics_user",
        display_name="analytics_user",
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


def _build_service(
    *,
    react_enabled: bool,
    react_gateway: MockLLMGateway | None = None,
) -> AnalyticsService:
    """构造带可选 ReAct 依赖的 AnalyticsService。"""

    settings = Settings(analytics_react_planner_enabled=react_enabled, analytics_react_max_steps=3)
    schema_registry = SchemaRegistry(settings=settings)
    metric_catalog = MetricCatalog(
        default_data_source=schema_registry.get_default_data_source().key,
        default_table_name=schema_registry.get_default_data_source().default_table,
    )
    base_planner = AnalyticsPlanner(
        metric_catalog=metric_catalog,
        llm_planner_gateway=LLMAnalyticsPlannerGateway(settings=settings),
    )
    react_planner = None
    if react_gateway is not None:
        react_planner = AnalyticsReactPlanner(
            base_planner=base_planner,
            tool_registry=AnalyticsReactToolRegistry(
                metric_catalog=metric_catalog,
                schema_registry=schema_registry,
            ),
            llm_gateway=react_gateway,
            settings=settings,
        )
    return AnalyticsService(
        conversation_repository=ConversationRepository(session=None),
        task_run_repository=TaskRunRepository(session=None),
        sql_audit_repository=SQLAuditRepository(session=None),
        analytics_planner=base_planner,
        sql_builder=SQLBuilder(schema_registry=schema_registry, metric_catalog=metric_catalog),
        sql_guard=SQLGuard(allowed_tables=["analytics_metrics_daily"]),
        sql_gateway=SQLGateway(schema_registry=schema_registry),
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
        analytics_react_policy=AnalyticsReactPlanningPolicy(settings=settings),
        analytics_react_planner=react_planner,
    )


def test_simple_question_does_not_use_react() -> None:
    """简单问题应继续走确定性 Planner。"""

    workflow = AnalyticsLangGraphWorkflow(_build_service(react_enabled=True))

    state = workflow.run_state(
        query="帮我分析一下上个月新疆区域发电量",
        user_context=_user_context(),
        output_mode="lite",
    )

    assert state["final_response"]["meta"]["status"] == "succeeded"
    assert state["react_used"] is False
    assert state["plan"].planning_source == "rule"


def test_react_disabled_never_uses_react_even_for_complex_question() -> None:
    """开关关闭时，复杂问题也必须走确定性 Planner。"""

    gateway = MockLLMGateway(
        structured_payload={
            "thought": "不应该被调用",
            "action": "finish",
            "final_plan_candidate": {
                "slots": {"metric": "收入", "time_range": {"label": "上个月"}},
                "confidence": 0.9,
                "reason": "disabled",
            },
        }
    )
    workflow = AnalyticsLangGraphWorkflow(_build_service(react_enabled=False, react_gateway=gateway))

    state = workflow.run_state(
        query="帮我做一下上个月收入同比对比",
        user_context=_user_context(),
        output_mode="lite",
    )

    assert state["react_used"] is False
    assert len(gateway.calls) == 0
    assert state["final_response"]["meta"]["status"] == "succeeded"


def test_complex_question_uses_react_and_keeps_sql_guard_chain() -> None:
    """复杂问题可走 ReAct，但后续仍会经过 SQL Guard / SQL Gateway。"""

    gateway = MockLLMGateway(
        structured_payload={
            "thought": "收入同比需要对比目标和月度维度",
            "action": "finish",
            "action_input": {},
            "final_plan_candidate": {
                "slots": {
                    "metric": "收入",
                    "time_range": {
                        "type": "explicit_month",
                        "label": "2024-03",
                        "start_date": "2024-03-01",
                        "end_date": "2024-03-31",
                    },
                    "compare_target": "yoy",
                    "group_by": "month",
                },
                "confidence": 0.93,
                "reason": "复杂对比表达",
            },
            "stopped_reason": "finished",
        }
    )
    workflow = AnalyticsLangGraphWorkflow(_build_service(react_enabled=True, react_gateway=gateway))

    state = workflow.run_state(
        query="帮我做一下收入同比对比",
        user_context=_user_context(),
        output_mode="lite",
    )

    assert state["react_used"] is True
    assert state["react_fallback_used"] is False
    assert state["plan"].planning_source == "react_planner"
    assert state["guard_result"].is_safe is True
    assert state["execution_result"].row_count >= 0
    assert state["final_response"]["meta"]["react_used"] is True


def test_react_failure_falls_back_to_rule_planner() -> None:
    """ReAct 失败时应回退到现有 AnalyticsPlanner。"""

    gateway = MockLLMGateway(response_content="不是 JSON")
    workflow = AnalyticsLangGraphWorkflow(_build_service(react_enabled=True, react_gateway=gateway))

    state = workflow.run_state(
        query="帮我做一下上个月收入同比对比",
        user_context=_user_context(),
        output_mode="lite",
    )

    assert state["react_used"] is True
    assert state["react_fallback_used"] is True
    assert state["plan"].planning_source == "rule"
    assert state["final_response"]["meta"]["status"] == "succeeded"
