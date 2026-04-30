"""经营分析上游 snapshot 写入边界测试。"""

from __future__ import annotations

import pytest

from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
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


def build_user_context(user_id: int = 2301) -> UserContext:
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


def build_service() -> AnalyticsService:
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
        sql_builder=SQLBuilder(schema_registry=schema_registry, metric_catalog=metric_catalog),
        sql_guard=SQLGuard(allowed_tables=["analytics_metrics_daily"]),
        sql_gateway=SQLGateway(schema_registry=schema_registry),
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )


def test_analytics_service_writes_only_lightweight_task_run_snapshots() -> None:
    """AnalyticsService 上游写入 task_run 时不应直接塞入微观大对象。"""

    service = build_service()
    result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    run_id = result["meta"]["run_id"]
    task_run = service.task_run_repository.get_task_run(run_id)
    heavy_result = service.analytics_result_repository.get_heavy_result(run_id)
    assert task_run is not None
    assert heavy_result is not None

    input_snapshot = task_run["input_snapshot"]
    assert input_snapshot["query"] == "帮我分析一下上个月新疆区域发电量"
    assert input_snapshot["conversation_id"] == result["meta"]["conversation_id"]
    assert input_snapshot["user_context_summary"]["department_code"] == "analytics-center"
    assert "plan" not in input_snapshot
    assert "sql_bundle" not in input_snapshot
    assert "execution_result" not in input_snapshot
    assert "workflow_stage" not in input_snapshot

    output_snapshot = task_run["output_snapshot"]
    assert output_snapshot["summary"]
    assert output_snapshot["row_count"] is not None
    assert output_snapshot["latency_ms"] is not None
    assert output_snapshot["sql_preview"]
    assert output_snapshot["slots"]["metric"] == "发电量"
    assert "tables" not in output_snapshot
    assert "chart_spec" not in output_snapshot
    assert "insight_cards" not in output_snapshot
    assert "report_blocks" not in output_snapshot
    assert "execution_result" not in output_snapshot
    assert "sql_bundle" not in output_snapshot
    assert "workflow_stage" not in output_snapshot

    context_snapshot = task_run["context_snapshot"]
    assert context_snapshot["slots"]["metric"] == "发电量"
    assert context_snapshot["planning_source"] == "rule"
    assert "plan" not in context_snapshot
    assert "sql_bundle" not in context_snapshot
    assert "execution_result" not in context_snapshot
    assert "workflow_outcome" not in context_snapshot

    assert heavy_result["tables"]
    assert heavy_result["chart_spec"] is not None


def test_analytics_service_clarification_writes_only_recovery_snapshots() -> None:
    """clarification 分支只应写 slot_snapshot 和 clarification_event 必需字段。"""

    service = build_service()
    result = service.submit_query(
        query="帮我分析一下上个月的情况",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=build_user_context(user_id=2302),
    )

    run_id = result["meta"]["run_id"]
    clarification = result["data"]["clarification"]
    task_run = service.task_run_repository.get_task_run(run_id)
    slot_snapshot = service.task_run_repository.get_slot_snapshot(run_id)
    clarification_event = service.task_run_repository.get_clarification_event(
        clarification["clarification_id"],
    )

    assert task_run is not None
    assert slot_snapshot is not None
    assert clarification_event is not None

    context_snapshot = task_run["context_snapshot"]
    assert context_snapshot["slots"]["time_range"]["label"] == "上个月"
    assert context_snapshot["missing_slots"] == ["metric"]
    assert context_snapshot["clarification_type"] == "missing_required_slot"
    assert context_snapshot["resume_step"] == "resume_after_analytics_slot_fill"
    assert "plan" not in context_snapshot
    assert "sql_bundle" not in context_snapshot
    assert "execution_result" not in context_snapshot

    assert set(slot_snapshot.keys()) == {
        "run_id",
        "task_type",
        "required_slots",
        "collected_slots",
        "missing_slots",
        "min_executable_satisfied",
        "awaiting_user_input",
        "resume_step",
        "updated_at",
    }
    assert slot_snapshot["missing_slots"] == ["metric"]

    assert set(clarification_event.keys()) == {
        "clarification_id",
        "run_id",
        "conversation_id",
        "question_text",
        "target_slots",
        "user_reply",
        "resolved_slots",
        "status",
        "created_at",
        "resolved_at",
    }
    assert clarification_event["target_slots"] == ["metric"]
