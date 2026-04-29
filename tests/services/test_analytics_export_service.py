"""AnalyticsExportService 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.config.settings import Settings
from core.repositories.analytics_export_repository import (
    AnalyticsExportRepository,
    reset_in_memory_analytics_export_store,
)
from core.repositories.conversation_repository import ConversationRepository, reset_in_memory_conversation_store
from core.repositories.sql_audit_repository import SQLAuditRepository, reset_in_memory_sql_audit_store
from core.repositories.task_run_repository import TaskRunRepository, reset_in_memory_task_run_store
from core.security.auth import UserContext
from core.services.analytics_export_service import AnalyticsExportService
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
    yield
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_analytics_export_store()


def build_user_context(user_id: int = 1501) -> UserContext:
    """构造最小测试用户上下文。"""

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


def build_services(tmp_path: Path) -> tuple[AnalyticsService, AnalyticsExportService]:
    """构造共享仓储的 analytics/export service。"""

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
        analytics_export_repository=AnalyticsExportRepository(session=None),
        report_gateway=ReportGateway(settings=settings),
    )
    return analytics_service, export_service


def test_analytics_export_service_creates_export_from_existing_run(tmp_path: Path) -> None:
    """基于已完成的 analytics run 应能成功创建导出任务。"""

    analytics_service, export_service = build_services(tmp_path)
    user_context = build_user_context()
    analytics_result = analytics_service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="summary",
        need_sql_explain=True,
        user_context=user_context,
    )

    export_result = export_service.create_export(
        run_id=analytics_result["meta"]["run_id"],
        export_type="markdown",
        user_context=user_context,
    )

    assert export_result["meta"]["status"] == "succeeded"
    assert export_result["data"]["run_id"] == analytics_result["meta"]["run_id"]
    assert export_result["data"]["export_type"] == "markdown"
    assert export_result["data"]["filename"].endswith(".md")
    assert Path(export_result["data"]["artifact_path"]).exists()


def test_analytics_export_service_can_read_export_detail(tmp_path: Path) -> None:
    """导出任务创建后，应能通过 export_id 读取详情。"""

    analytics_service, export_service = build_services(tmp_path)
    user_context = build_user_context(user_id=1502)
    analytics_result = analytics_service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="summary",
        need_sql_explain=False,
        user_context=user_context,
    )
    export_result = export_service.create_export(
        run_id=analytics_result["meta"]["run_id"],
        export_type="json",
        user_context=user_context,
    )

    detail = export_service.get_export_detail(
        export_id=export_result["data"]["export_id"],
        user_context=user_context,
    )

    assert detail["data"]["export_id"] == export_result["data"]["export_id"]
    assert detail["data"]["status"] == "succeeded"
    assert detail["data"]["metadata"]["server_mode"] == "inprocess_report_mcp_server"
