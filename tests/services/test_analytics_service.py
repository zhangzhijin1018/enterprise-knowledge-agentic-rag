"""AnalyticsService 测试。"""

from __future__ import annotations

import pytest

from core.common.cache import reset_global_cache
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.repositories.analytics_result_repository import (
    reset_in_memory_analytics_result_store,
)
from core.repositories.data_source_repository import reset_in_memory_data_source_store
from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.common.exceptions import AppException
from core.config.settings import Settings
from core.repositories.conversation_repository import ConversationRepository, reset_in_memory_conversation_store
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


def build_user_context(user_id: int = 1201) -> UserContext:
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


def build_service(
    *,
    analytics_planner_gateway: LLMAnalyticsPlannerGateway | None = None,
) -> AnalyticsService:
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
            llm_planner_gateway=analytics_planner_gateway,
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


def test_analytics_service_runs_successfully_when_metric_and_time_range_are_present() -> None:
    """metric + time_range 齐全时应进入执行链路并成功返回摘要。"""

    service = build_service()

    result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    assert result["meta"]["status"] == "succeeded"
    assert "summary" in result["data"]
    assert result["data"]["tables"]
    assert result["data"]["sql_preview"] is not None
    assert result["data"]["metric_scope"] == "发电量"
    assert result["data"]["data_source"] == "local_analytics"
    assert result["data"]["row_count"] is not None
    assert result["data"]["latency_ms"] is not None
    assert result["data"]["group_by"] is None
    assert result["data"]["compare_target"] is None
    assert result["data"]["chart_spec"] is not None
    assert result["data"]["chart_spec"]["chart_type"] in {"stacked_bar", "pie", "line", "bar", "ranking_bar"}
    assert result["data"]["insight_cards"]
    assert result["data"]["report_blocks"]
    assert result["data"]["audit_info"] is not None
    assert result["data"]["permission_check_result"] is not None
    assert result["data"]["data_scope_result"]["enforced"] is True
    assert result["data"]["effective_filters"]["department_code"] == "analytics-center"
    assert "governance_decision" in result["data"]


def test_analytics_service_returns_clarification_when_metric_missing() -> None:
    """缺少 metric 时应返回澄清。"""

    service = build_service()

    result = service.submit_query(
        query="帮我分析一下上个月的情况",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    assert result["meta"]["status"] == "awaiting_user_clarification"
    assert result["data"]["clarification"]["target_slots"] == ["metric"]
    assert result["data"]["clarification"]["clarification_type"] == "missing_required_slot"
    assert result["data"]["clarification"]["reason"] is not None
    assert result["data"]["clarification"]["suggested_options"]


def test_analytics_service_blocks_query_without_time_range() -> None:
    """缺少 time_range 时也必须澄清，不能直接执行 SQL。"""

    service = build_service()

    result = service.submit_query(
        query="帮我分析一下新疆区域发电量",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=build_user_context(),
    )

    assert result["meta"]["status"] == "awaiting_user_clarification"
    assert result["data"]["clarification"]["target_slots"] == ["time_range"]
    assert result["data"]["clarification"]["clarification_type"] == "missing_required_slot"


def test_analytics_service_get_run_detail_contains_sql_audit() -> None:
    """成功执行后，运行详情应能看到最新 SQL 审计。"""

    service = build_service()

    submit_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=True,
        user_context=build_user_context(),
    )
    run_id = submit_result["meta"]["run_id"]

    detail_result = service.get_run_detail(
        run_id=run_id,
        output_mode="full",
        user_context=build_user_context(),
    )

    assert detail_result["data"]["latest_sql_audit"] is not None
    assert detail_result["data"]["latest_sql_audit"]["is_safe"] is True
    assert detail_result["data"]["data_source"] == "local_analytics"
    assert detail_result["data"]["chart_spec"] is not None
    assert detail_result["data"]["insight_cards"]
    assert detail_result["data"]["report_blocks"]
    assert detail_result["data"]["audit_info"] is not None


def test_analytics_service_raises_for_unauthorized_run_detail() -> None:
    """不同用户不应查看他人的经营分析运行详情。"""

    service = build_service()

    submit_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=build_user_context(user_id=1201),
    )

    with pytest.raises(AppException):
        service.get_run_detail(
            run_id=submit_result["meta"]["run_id"],
            user_context=build_user_context(user_id=1202),
        )


def test_analytics_service_supports_multi_turn_slot_inheritance_and_update() -> None:
    """多轮分析应支持继承上一轮上下文并增量更新槽位。"""

    service = build_service()
    user_context = build_user_context(user_id=1203)

    first_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=user_context,
    )
    conversation_id = first_result["meta"]["conversation_id"]

    second_result = service.submit_query(
        query="再按月看",
        conversation_id=conversation_id,
        output_mode="full",
        need_sql_explain=False,
        user_context=user_context,
    )

    assert second_result["meta"]["status"] == "succeeded"
    assert second_result["data"]["tables"]
    first_table = second_result["data"]["tables"][0]
    assert "month" in first_table["columns"]
    assert second_result["data"]["metric_scope"] == "发电量"
    assert second_result["data"]["group_by"] == "month"
    assert second_result["data"]["chart_spec"]["chart_type"] == "line"


def test_analytics_service_supports_incremental_metric_switch() -> None:
    """多轮分析时应支持换指标并继承时间范围。"""

    service = build_service()
    user_context = build_user_context(user_id=1204)

    first_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )
    conversation_id = first_result["meta"]["conversation_id"]

    second_result = service.submit_query(
        query="换成收入",
        conversation_id=conversation_id,
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )

    assert second_result["meta"]["status"] == "succeeded"
    assert second_result["data"]["metric_scope"] == "收入"


def test_analytics_service_supports_compare_inheritance_query() -> None:
    """“再看一下同比”应尽量继承上一轮上下文直接执行。"""

    service = build_service()
    user_context = build_user_context(user_id=1207)

    first_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )

    second_result = service.submit_query(
        query="再看一下同比",
        conversation_id=first_result["meta"]["conversation_id"],
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )

    assert second_result["meta"]["status"] == "succeeded"
    assert second_result["data"]["compare_target"] == "yoy"


def test_analytics_service_supports_org_scope_switch_query() -> None:
    """“新疆换成北疆”应继承主指标与时间范围，只覆盖组织范围。"""

    service = build_service()
    user_context = build_user_context(user_id=1208)

    first_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )

    second_result = service.submit_query(
        query="新疆换成北疆",
        conversation_id=first_result["meta"]["conversation_id"],
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )

    assert second_result["meta"]["status"] == "succeeded"
    assert "北疆区域" in second_result["data"]["summary"]


def test_analytics_service_supports_station_scope_switch_query() -> None:
    """“只看哈密电站”应继承上一轮上下文并缩小组织范围。"""

    service = build_service()
    user_context = build_user_context(user_id=1209)

    first_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )

    second_result = service.submit_query(
        query="只看哈密电站",
        conversation_id=first_result["meta"]["conversation_id"],
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )

    assert second_result["meta"]["status"] == "succeeded"
    assert "哈密电站" in second_result["data"]["summary"]


def test_analytics_service_returns_conflict_clarification_for_multi_metric_follow_up() -> None:
    """“再把成本也加进来”当前阶段应澄清主指标，而不是直接执行。"""

    service = build_service()
    user_context = build_user_context(user_id=1210)

    first_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )

    second_result = service.submit_query(
        query="再把成本也加进来",
        conversation_id=first_result["meta"]["conversation_id"],
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )

    assert second_result["meta"]["status"] == "awaiting_user_clarification"
    assert second_result["data"]["clarification"]["clarification_type"] == "slot_conflict"
    assert second_result["data"]["clarification"]["suggested_options"] == ["发电量", "成本"]


def test_analytics_service_supports_compare_and_topn_query() -> None:
    """compare / topN 的最小链路应可运行。"""

    service = build_service()

    result = service.submit_query(
        query="最近发电表现按站点排名前3做环比",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=True,
        user_context=build_user_context(user_id=1205),
    )

    assert result["meta"]["status"] == "succeeded"
    assert result["data"]["compare_target"] == "mom"
    assert result["data"]["group_by"] == "station"
    assert result["data"]["sql_preview"] is not None
    assert result["data"]["chart_spec"]["chart_type"] == "ranking_bar"


def test_analytics_service_can_use_llm_fallback_for_low_confidence_query() -> None:
    """规则不足但语义明显时，应允许 LLM fallback 补强槽位。"""

    def mock_planner_callable(*, query: str, current_slots: dict, conversation_memory: dict) -> dict:
        return {
            "slots": {
                "metric": "利润",
                "time_range": {
                    "type": "relative_30_days",
                    "label": "近一个月",
                    "start_date": "2024-03-02",
                    "end_date": "2024-04-01",
                },
            },
            "confidence": 0.95,
            "source": "mock_llm",
            "should_use": True,
        }

    service = build_service(
        analytics_planner_gateway=LLMAnalyticsPlannerGateway(
            settings=Settings(analytics_planner_enable_llm_fallback=True),
            planner_callable=mock_planner_callable,
        )
    )

    result = service.submit_query(
        query="最近经营表现怎么样",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=False,
        user_context=build_user_context(user_id=1206),
    )

    assert result["meta"]["status"] == "succeeded"
    assert result["data"]["metric_scope"] == "利润"


def test_analytics_service_rejects_metric_without_permission() -> None:
    """缺少指标权限时应返回明确的指标权限拒绝。"""

    service = build_service()
    user_context = build_user_context(user_id=1211)
    user_context.permissions = ["analytics:query", "analytics:metric:generation"]

    with pytest.raises(AppException) as exc_info:
        service.submit_query(
            query="帮我分析一下上个月新疆区域收入",
            conversation_id=None,
            output_mode="standard",
            need_sql_explain=False,
            user_context=user_context,
        )

    assert exc_info.value.error_code == "ANALYTICS_METRIC_PERMISSION_DENIED"


def test_analytics_service_rejects_data_source_without_permission() -> None:
    """缺少数据源权限时应被明确拒绝。"""

    schema_registry = SchemaRegistry()
    default_source = schema_registry.get_default_data_source()
    default_source.required_permissions = ["analytics:query", "analytics:source:local_analytics"]
    metric_catalog = MetricCatalog(
        default_data_source=default_source.key,
        default_table_name=default_source.default_table,
    )
    service = AnalyticsService(
        conversation_repository=ConversationRepository(session=None),
        task_run_repository=TaskRunRepository(session=None),
        sql_audit_repository=SQLAuditRepository(session=None),
        analytics_planner=AnalyticsPlanner(metric_catalog=metric_catalog),
        sql_builder=SQLBuilder(schema_registry=schema_registry, metric_catalog=metric_catalog),
        sql_guard=SQLGuard(allowed_tables=["analytics_metrics_daily"]),
        sql_gateway=SQLGateway(schema_registry=schema_registry),
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )

    with pytest.raises(AppException) as exc_info:
        service.submit_query(
            query="帮我分析一下上个月新疆区域发电量",
            conversation_id=None,
            output_mode="standard",
            need_sql_explain=False,
            user_context=build_user_context(user_id=1212),
        )

    assert exc_info.value.error_code == "ANALYTICS_DATA_SOURCE_PERMISSION_DENIED"


def test_analytics_service_masks_sensitive_fields_when_permission_missing() -> None:
    """命中敏感字段时，结果应按最小规则脱敏。"""

    service = build_service()

    result = service.submit_query(
        query="最近发电表现按站点排名前3",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=build_user_context(user_id=1213),
    )

    assert result["meta"]["status"] == "succeeded"
    assert "station" in result["data"]["masked_fields"]
    first_table = result["data"]["tables"][0]
    assert "station" in first_table["columns"]
    assert any("***" in str(cell) for row in first_table["rows"] for cell in row)


def test_analytics_service_supports_tiered_output_modes() -> None:
    """lite / standard / full 应返回不同粒度的数据。"""

    service = build_service()
    user_context = build_user_context(user_id=1214)

    lite_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="lite",
        need_sql_explain=False,
        user_context=user_context,
    )
    standard_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="standard",
        need_sql_explain=False,
        user_context=user_context,
    )
    full_result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=user_context,
    )

    assert lite_result["meta"]["status"] == "succeeded"
    assert "summary" in lite_result["data"]
    assert "chart_spec" not in lite_result["data"]
    assert "tables" not in lite_result["data"]

    assert standard_result["meta"]["status"] == "succeeded"
    assert standard_result["data"]["chart_spec"] is not None
    assert standard_result["data"]["insight_cards"]
    assert "tables" not in standard_result["data"]
    assert "report_blocks" not in standard_result["data"]

    assert full_result["meta"]["status"] == "succeeded"
    assert full_result["data"]["chart_spec"] is not None
    assert full_result["data"]["insight_cards"]
    assert full_result["data"]["tables"]
    assert full_result["data"]["report_blocks"]


def test_analytics_service_compacts_output_snapshot_and_splits_heavy_result() -> None:
    """output_snapshot 应只保留轻快照，重结果单独写入结果仓储。"""

    service = build_service()
    result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=build_user_context(user_id=1215),
    )
    run_id = result["meta"]["run_id"]
    task_run = service.task_run_repository.get_task_run(run_id)
    heavy_result = service.analytics_result_repository.get_heavy_result(run_id)

    assert task_run is not None
    assert heavy_result is not None

    output_snapshot = task_run["output_snapshot"]
    assert output_snapshot["summary"]
    assert output_snapshot["sql_preview"]
    assert output_snapshot["has_heavy_result"] is True
    assert "tables" not in output_snapshot
    assert "insight_cards" not in output_snapshot
    assert "report_blocks" not in output_snapshot
    assert "chart_spec" not in output_snapshot
    assert output_snapshot["timing_breakdown"]["sql_execute_ms"] >= 0

    assert heavy_result["tables"]
    assert heavy_result["insight_cards"]
    assert heavy_result["report_blocks"]
    assert heavy_result["chart_spec"] is not None


def test_analytics_service_records_timing_breakdown() -> None:
    """关键阶段耗时应写入 timing_breakdown，便于后续性能排查。"""

    service = build_service()
    result = service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=build_user_context(user_id=1216),
    )

    timing = result["data"]["timing_breakdown"]
    assert timing["sql_build_ms"] >= 0
    assert timing["sql_guard_ms"] >= 0
    assert timing["sql_execute_ms"] >= 0
    assert timing["masking_ms"] >= 0
    assert timing["insight_ms"] >= 0
    assert timing["report_ms"] >= 0
