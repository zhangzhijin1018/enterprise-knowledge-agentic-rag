"""AnalyticsReviewService 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.analytics_review_policy import AnalyticsReviewPolicy
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.config.settings import Settings
from core.repositories.analytics_export_repository import (
    AnalyticsExportRepository,
    reset_in_memory_analytics_export_store,
)
from core.repositories.analytics_review_repository import (
    AnalyticsReviewRepository,
    reset_in_memory_analytics_review_store,
)
from core.repositories.conversation_repository import ConversationRepository, reset_in_memory_conversation_store
from core.repositories.sql_audit_repository import SQLAuditRepository, reset_in_memory_sql_audit_store
from core.repositories.task_run_repository import TaskRunRepository, reset_in_memory_task_run_store
from core.security.auth import UserContext
from core.services.analytics_export_service import AnalyticsExportService
from core.services.analytics_review_service import AnalyticsReviewService
from core.services.analytics_service import AnalyticsService
from core.tools.report.report_gateway import ReportGateway
from core.tools.sql.sql_gateway import SQLGateway


@pytest.fixture(autouse=True)
def reset_state() -> None:
    """重置测试使用的内存状态。"""

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_analytics_export_store()
    reset_in_memory_analytics_review_store()
    yield
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_analytics_export_store()
    reset_in_memory_analytics_review_store()


def build_user_context(
    user_id: int = 1601,
    *,
    permissions: list[str] | None = None,
    roles: list[str] | None = None,
) -> UserContext:
    """构造最小测试用户上下文。"""

    return UserContext(
        user_id=user_id,
        username=f"user_{user_id}",
        display_name=f"user_{user_id}",
        roles=roles or ["employee", "analyst"],
        department_code="analytics-center",
        permissions=permissions
        or [
            "analytics:query",
            "analytics:metric:generation",
            "analytics:metric:revenue",
            "analytics:metric:cost",
            "analytics:metric:profit",
            "analytics:metric:output",
        ],
    )


def build_services(tmp_path: Path) -> tuple[AnalyticsService, AnalyticsExportService, AnalyticsReviewService]:
    """构造共享仓储的 analytics/export/review service。"""

    settings = Settings(
        local_export_dir=str(tmp_path),
        analytics_report_gateway_transport_mode="inprocess_report_mcp_server",
    )
    schema_registry = SchemaRegistry(settings=settings)
    metric_catalog = MetricCatalog(
        default_data_source=schema_registry.get_default_data_source().key,
        default_table_name=schema_registry.get_default_data_source().default_table,
    )
    conversation_repository = ConversationRepository(session=None)
    task_run_repository = TaskRunRepository(session=None)
    export_repository = AnalyticsExportRepository(session=None)
    review_repository = AnalyticsReviewRepository(session=None)
    review_policy = AnalyticsReviewPolicy(high_row_count_threshold=100)

    analytics_service = AnalyticsService(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
        sql_audit_repository=SQLAuditRepository(session=None),
        analytics_planner=AnalyticsPlanner(
            metric_catalog=metric_catalog,
            llm_planner_gateway=LLMAnalyticsPlannerGateway(settings=settings),
        ),
        sql_builder=SQLBuilder(
            schema_registry=schema_registry,
            metric_catalog=metric_catalog,
        ),
        sql_guard=SQLGuard(allowed_tables=["analytics_metrics_daily"]),
        sql_gateway=SQLGateway(schema_registry=schema_registry, settings=settings),
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )
    export_service = AnalyticsExportService(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
        analytics_export_repository=export_repository,
        analytics_review_repository=review_repository,
        report_gateway=ReportGateway(settings=settings),
        review_policy=review_policy,
    )
    review_service = AnalyticsReviewService(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
        analytics_export_repository=export_repository,
        analytics_review_repository=review_repository,
        analytics_export_service=export_service,
    )
    return analytics_service, export_service, review_service


def test_normal_export_does_not_trigger_review(tmp_path: Path) -> None:
    """普通 markdown 导出应直接成功，不触发 review。"""

    analytics_service, export_service, _review_service = build_services(tmp_path)
    user_context = build_user_context()
    analytics_result = analytics_service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="summary",
        need_sql_explain=False,
        user_context=user_context,
    )

    export_result = export_service.create_export(
        run_id=analytics_result["meta"]["run_id"],
        export_type="markdown",
        user_context=user_context,
    )

    assert export_result["meta"]["status"] == "succeeded"
    assert export_result["data"]["review_required"] is False
    assert export_result["data"]["review_status"] == "not_required"


def test_high_risk_export_triggers_review_then_can_be_approved(tmp_path: Path) -> None:
    """高风险导出应先进入 awaiting_human_review，审批通过后继续导出。"""

    analytics_service, export_service, review_service = build_services(tmp_path)
    owner_context = build_user_context(user_id=1602)
    reviewer_context = build_user_context(
        user_id=2602,
        permissions=[
            "analytics:query",
            "analytics:review",
            "analytics:metric:generation",
            "analytics:metric:revenue",
            "analytics:metric:cost",
            "analytics:metric:profit",
            "analytics:metric:output",
        ],
        roles=["manager", "analyst"],
    )
    analytics_result = analytics_service.submit_query(
        query="帮我分析一下上个月新疆区域收入",
        conversation_id=None,
        output_mode="summary",
        need_sql_explain=False,
        user_context=owner_context,
    )

    export_result = export_service.create_export(
        run_id=analytics_result["meta"]["run_id"],
        export_type="pdf",
        user_context=owner_context,
    )

    assert export_result["meta"]["status"] == "awaiting_human_review"
    assert export_result["data"]["review_required"] is True
    assert export_result["data"]["review_status"] == "pending"

    approved_result = review_service.approve_review(
        review_id=export_result["data"]["review_id"],
        comment="审批通过，可以生成正式版本。",
        reviewer_context=reviewer_context,
    )

    assert approved_result["data"]["review"]["review_status"] == "approved"
    assert approved_result["data"]["export"]["status"] == "succeeded"
    assert approved_result["data"]["export"]["review_status"] == "approved"


def test_high_risk_export_can_be_rejected(tmp_path: Path) -> None:
    """高风险导出被驳回后应终止。"""

    analytics_service, export_service, review_service = build_services(tmp_path)
    owner_context = build_user_context(user_id=1603)
    reviewer_context = build_user_context(
        user_id=2603,
        permissions=[
            "analytics:query",
            "analytics:review",
            "analytics:metric:generation",
            "analytics:metric:revenue",
            "analytics:metric:cost",
            "analytics:metric:profit",
            "analytics:metric:output",
        ],
        roles=["manager", "analyst"],
    )
    analytics_result = analytics_service.submit_query(
        query="帮我分析一下上个月新疆区域收入",
        conversation_id=None,
        output_mode="summary",
        need_sql_explain=False,
        user_context=owner_context,
    )
    export_result = export_service.create_export(
        run_id=analytics_result["meta"]["run_id"],
        export_type="docx",
        user_context=owner_context,
    )

    rejected_result = review_service.reject_review(
        review_id=export_result["data"]["review_id"],
        comment="当前正式导出结论需要进一步复核，先驳回。",
        reviewer_context=reviewer_context,
    )

    assert rejected_result["data"]["review"]["review_status"] == "rejected"
    assert rejected_result["data"]["export"]["status"] == "failed"
    assert rejected_result["data"]["export"]["review_status"] == "rejected"
