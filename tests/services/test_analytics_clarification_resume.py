"""经营分析 clarification 恢复测试。"""

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
from core.config.settings import Settings
from core.repositories.analytics_result_repository import reset_in_memory_analytics_result_store
from core.repositories.conversation_repository import ConversationRepository, reset_in_memory_conversation_store
from core.repositories.data_source_repository import reset_in_memory_data_source_store
from core.repositories.sql_audit_repository import SQLAuditRepository, reset_in_memory_sql_audit_store
from core.repositories.task_run_repository import TaskRunRepository, reset_in_memory_task_run_store
from core.security.auth import UserContext
from core.services.analytics_clarification_service import AnalyticsClarificationService
from core.services.analytics_service import AnalyticsService
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


def build_user_context(user_id: int = 2601) -> UserContext:
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
    service = AnalyticsService(
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
    service.bind_workflow_adapter(
        AnalyticsWorkflowAdapter(analytics_service=service),
        use_workflow=True,
    )
    return service


def test_analytics_clarification_reply_can_resume_with_original_run_id() -> None:
    """补齐槽位后应复用原 run_id 恢复执行，而不是新建无关 run。"""

    service = build_service()
    user_context = build_user_context()
    clarification_service = AnalyticsClarificationService(
        conversation_repository=service.conversation_repository,
        task_run_repository=service.task_run_repository,
        analytics_service=service,
    )

    first_result = service.submit_query(
        query="帮我分析一下上个月的情况",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )
    clarification_id = first_result["data"]["clarification"]["clarification_id"]
    original_run_id = first_result["meta"]["run_id"]

    resumed_result = clarification_service.reply(
        clarification_id=clarification_id,
        reply="发电量",
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )

    task_run = service.task_run_repository.get_task_run(original_run_id)
    clarification_event = service.task_run_repository.get_clarification_event(clarification_id)
    slot_snapshot = service.task_run_repository.get_slot_snapshot(original_run_id)

    assert resumed_result["meta"]["status"] == "succeeded"
    assert resumed_result["meta"]["run_id"] == original_run_id
    assert resumed_result["data"]["summary"]
    assert task_run is not None
    assert task_run["run_id"] == original_run_id
    assert task_run["status"] == "succeeded"
    assert clarification_event is not None
    assert clarification_event["status"] == "resolved"
    assert clarification_event["resolved_slots"]["metric"] == "发电量"
    assert slot_snapshot is not None
    assert slot_snapshot["min_executable_satisfied"] is True
    assert slot_snapshot["awaiting_user_input"] is False
    assert slot_snapshot["collected_slots"]["metric"] == "发电量"


def test_analytics_clarification_reply_returns_new_clarification_when_slots_still_missing() -> None:
    """如果用户补充后仍不满足最小可执行条件，应继续 clarification 而不是假成功。"""

    service = build_service()
    user_context = build_user_context(user_id=2602)
    clarification_service = AnalyticsClarificationService(
        conversation_repository=service.conversation_repository,
        task_run_repository=service.task_run_repository,
        analytics_service=service,
    )

    first_result = service.submit_query(
        query="帮我分析一下上个月的情况",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=user_context,
    )
    clarification_id = first_result["data"]["clarification"]["clarification_id"]
    original_run_id = first_result["meta"]["run_id"]

    resumed_result = clarification_service.reply(
        clarification_id=clarification_id,
        reply="看一下",
        output_mode="lite",
        need_sql_explain=False,
        user_context=user_context,
    )

    slot_snapshot = service.task_run_repository.get_slot_snapshot(original_run_id)
    original_clarification = service.task_run_repository.get_clarification_event(clarification_id)

    assert resumed_result["meta"]["status"] == "awaiting_user_clarification"
    assert resumed_result["meta"]["run_id"] == original_run_id
    assert resumed_result["data"]["clarification"]["target_slots"] == ["metric"]
    assert slot_snapshot is not None
    assert slot_snapshot["awaiting_user_input"] is True
    assert slot_snapshot["missing_slots"] == ["metric"]
    assert original_clarification is not None
    assert original_clarification["status"] == "resolved"
