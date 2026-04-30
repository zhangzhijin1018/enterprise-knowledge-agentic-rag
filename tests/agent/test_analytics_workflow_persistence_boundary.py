"""经营分析 workflow 持久化边界测试。"""

from __future__ import annotations

import pytest

from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.agent.workflows.analytics import AnalyticsWorkflowAdapter
from core.agent.workflows.analytics.state import AnalyticsWorkflowOutcome, AnalyticsWorkflowStage
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
from core.services.clarification_service import ClarificationService
from core.tools.sql.sql_gateway import SQLGateway
from apps.api.schemas.clarification import ClarificationReplyRequest


@pytest.fixture(autouse=True)
def reset_state() -> None:
    """重置内存态，避免测试之间相互污染。"""

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


def build_user_context(user_id: int = 2101) -> UserContext:
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


def test_analytics_workflow_keeps_micro_state_out_of_task_run() -> None:
    """微观 workflow 字段应保留在 state 中，而不是误写入 task_run。"""

    service = build_analytics_service()
    adapter = AnalyticsWorkflowAdapter(service)

    workflow_state = adapter.execute_state(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=build_user_context(),
    )
    run_id = workflow_state["run_id"]
    task_run = service.task_run_repository.get_task_run(run_id)
    heavy_result = service.analytics_result_repository.get_heavy_result(run_id)

    assert task_run is not None
    assert heavy_result is not None

    # 微观 workflow state 可以保留控制流和中间态。
    assert workflow_state["workflow_stage"] == AnalyticsWorkflowStage.ANALYTICS_FINISH
    assert workflow_state["workflow_outcome"] == AnalyticsWorkflowOutcome.FINISH
    assert workflow_state["sql_bundle"]["generated_sql"]
    assert workflow_state["execution_result"].rows
    assert workflow_state["permission_check_result"]["allowed"] is True
    assert workflow_state["data_scope_result"]["enforced"] is True
    assert workflow_state["timing"]["sql_execute_ms"] >= 0

    # 但 task_run 只保留轻量运行态，不保留这些微观大对象。
    output_snapshot = task_run["output_snapshot"]
    context_snapshot = task_run["context_snapshot"]
    assert "workflow_stage" not in output_snapshot
    assert "workflow_outcome" not in output_snapshot
    assert "sql_bundle" not in output_snapshot
    assert "execution_result" not in output_snapshot
    assert "tables" not in output_snapshot
    assert "report_blocks" not in output_snapshot
    assert "sql_bundle" not in context_snapshot
    assert "execution_result" not in context_snapshot
    assert "workflow_outcome" not in context_snapshot

    # 重结果继续交给 analytics_result_repository。
    assert heavy_result["tables"]
    assert heavy_result["insight_cards"]
    assert heavy_result["report_blocks"]
    assert heavy_result["chart_spec"] is not None


def test_analytics_workflow_clarification_path_keeps_recovery_boundary_clean() -> None:
    """澄清分支应仍可用，同时恢复态对象保持轻量。"""

    service = build_analytics_service()
    adapter = AnalyticsWorkflowAdapter(service)

    workflow_state = adapter.execute_state(
        query="帮我分析一下上个月的情况",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(user_id=2102),
    )

    run_id = workflow_state["run_id"]
    response = workflow_state["final_response"]
    task_run = service.task_run_repository.get_task_run(run_id)
    slot_snapshot = service.task_run_repository.get_slot_snapshot(run_id)
    clarification_id = response["data"]["clarification"]["clarification_id"]
    clarification_event = service.task_run_repository.get_clarification_event(clarification_id)

    assert response["meta"]["status"] == "awaiting_user_clarification"
    assert workflow_state["clarification_needed"] is True
    assert workflow_state["workflow_outcome"] == AnalyticsWorkflowOutcome.CLARIFY
    assert task_run is not None
    assert task_run["status"] == "awaiting_user_clarification"
    assert slot_snapshot is not None
    assert clarification_event is not None

    # slot_snapshot 只保留恢复执行必需字段。
    assert slot_snapshot["missing_slots"] == ["metric"]
    assert slot_snapshot["awaiting_user_input"] is True
    assert slot_snapshot["resume_step"] == "resume_after_analytics_slot_fill"
    assert "tables" not in slot_snapshot
    assert "report_blocks" not in slot_snapshot

    # clarification_event 只保留交互事件字段。
    assert clarification_event["question_text"]
    assert clarification_event["target_slots"] == ["metric"]
    assert clarification_event["status"] == "pending"
    assert "sql_bundle" not in clarification_event
    assert "chart_spec" not in clarification_event


def test_analytics_workflow_clarification_can_still_resume_after_boundary_tightening() -> None:
    """边界收紧后，澄清回复恢复链路仍应可用。"""

    service = build_analytics_service()
    adapter = AnalyticsWorkflowAdapter(service)

    workflow_state = adapter.execute_state(
        query="帮我分析一下上个月的情况",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(user_id=2103),
    )
    clarification_id = workflow_state["final_response"]["data"]["clarification"]["clarification_id"]

    clarification_service = ClarificationService(
        conversation_repository=service.conversation_repository,
        task_run_repository=service.task_run_repository,
    )
    reply_result = clarification_service.reply(
        clarification_id,
        ClarificationReplyRequest(reply="发电量"),
        build_user_context(user_id=2103),
    )

    run_id = workflow_state["run_id"]
    task_run = service.task_run_repository.get_task_run(run_id)
    slot_snapshot = service.task_run_repository.get_slot_snapshot(run_id)
    clarification_event = service.task_run_repository.get_clarification_event(clarification_id)

    assert reply_result["meta"]["status"] == "succeeded"
    assert task_run is not None
    assert slot_snapshot is not None
    assert clarification_event is not None
    assert slot_snapshot["min_executable_satisfied"] is True
    assert slot_snapshot["awaiting_user_input"] is False
    assert clarification_event["status"] == "resolved"
    assert task_run["output_snapshot"]["answer"]
    assert task_run["output_snapshot"]["resolved_slots"]["metric"] == "发电量"
    assert "tables" not in task_run["output_snapshot"]
    assert "report_blocks" not in task_run["output_snapshot"]
