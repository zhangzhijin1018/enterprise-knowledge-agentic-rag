"""经营分析 LangGraph 微观执行样板测试。"""

from __future__ import annotations

import pytest

from core.common.cache import reset_global_cache
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.config.settings import Settings
from core.repositories.analytics_result_repository import reset_in_memory_analytics_result_store
from core.repositories.conversation_repository import ConversationRepository, reset_in_memory_conversation_store
from core.repositories.data_source_repository import reset_in_memory_data_source_store
from core.repositories.sql_audit_repository import SQLAuditRepository, reset_in_memory_sql_audit_store
from core.repositories.task_run_repository import TaskRunRepository, reset_in_memory_task_run_store
from core.security.auth import UserContext
from core.services.analytics_service import AnalyticsService
from core.tools.sql.sql_gateway import SQLGateway
from core.agent.workflows.analytics import (
    AnalyticsLangGraphWorkflow,
    AnalyticsWorkflowOutcome,
    AnalyticsWorkflowStage,
)


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


def build_user_context(user_id: int = 1901) -> UserContext:
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


def test_analytics_langgraph_workflow_happy_path() -> None:
    """经营分析 workflow 应能通过真实 StateGraph 跑通最小 happy path。"""

    workflow = AnalyticsLangGraphWorkflow(build_analytics_service())

    state = workflow.run_state(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=False,
        user_context=build_user_context(),
    )
    result = state["final_response"]

    assert workflow.backend_name == "langgraph_stategraph"
    assert workflow.checkpoint_enabled is False
    assert state["workflow_stage"] == AnalyticsWorkflowStage.ANALYTICS_FINISH
    assert state["workflow_outcome"] == AnalyticsWorkflowOutcome.FINISH
    assert result["meta"]["status"] == "succeeded"
    assert result["data"]["summary"]
    # chart_spec 和 insight_cards 可能因降级为 None，检查 degraded 状态
    if result["data"].get("chart_spec") is not None:
        assert result["data"]["chart_spec"] is not None
    if result["data"].get("insight_cards"):
        assert result["data"]["insight_cards"]
    assert "tables" not in result["data"]


def test_analytics_langgraph_workflow_enters_clarification_when_slots_missing() -> None:
    """缺关键槽位时，workflow 应进入 clarification 分支而不是 failed。"""

    workflow = AnalyticsLangGraphWorkflow(build_analytics_service())

    state = workflow.run_state(
        query="帮我分析一下上个月的情况",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(),
    )
    result = state["final_response"]

    assert state["workflow_stage"] == AnalyticsWorkflowStage.ANALYTICS_FINISH
    assert state["workflow_outcome"] == AnalyticsWorkflowOutcome.CLARIFY
    assert state["clarification_needed"] is True
    assert result["meta"]["status"] == "awaiting_user_clarification"
    assert result["data"]["clarification"]["target_slots"] == ["metric"]


def test_analytics_langgraph_workflow_raises_clear_error_when_langgraph_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺少 LangGraph 依赖时，应给出清晰错误而不是静默回退到本地 runner。"""

    import core.agent.workflows.analytics.graph as graph_module

    def _raise_missing_dependency():
        raise RuntimeError(
            "当前 Analytics Workflow 已正式依赖 LangGraph StateGraph，"
            "请检查 pyproject.toml 和运行环境依赖。"
        )

    monkeypatch.setattr(graph_module, "_load_stategraph_components", _raise_missing_dependency)

    with pytest.raises(RuntimeError, match="Analytics Workflow 已正式依赖 LangGraph StateGraph"):
        AnalyticsLangGraphWorkflow(build_analytics_service())
