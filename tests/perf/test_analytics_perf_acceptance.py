"""经营分析第18轮性能验收测试。

本测试文件的目标不是做严格基准压测，而是做“工程验收”：
1. 验证 lite / standard / full 分级返回是否真的生效；
2. 验证 task_run.output_snapshot 是否真的完成轻量化；
3. 验证重内容是否已经拆到 analytics_result_repository；
4. 验证 export 是否已经具备真实异步任务语义；
5. 验证 registry/schema 只读缓存是否开始复用；
6. 基于 timing_breakdown 输出最小慢点复盘结论。

注意：
- 当前测试运行在本地 demo / in-memory 环境；
- 耗时结果用于“相对趋势验收”，不作为最终生产性能 SLA；
- 真正生产性能仍需要在 PostgreSQL 真实数据源上继续做 EXPLAIN ANALYZE 和压测。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from core.agent.control_plane.analytics_planner import AnalyticsPlanner
from core.agent.control_plane.analytics_review_policy import AnalyticsReviewPolicy
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.sql_builder import SQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.analytics.data_source_registry import DataSourceRegistry
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.common.async_task_runner import reset_async_task_runner
from core.common.cache import get_global_cache, reset_global_cache
from core.config.settings import Settings
from core.repositories.analytics_export_repository import (
    AnalyticsExportRepository,
    reset_in_memory_analytics_export_store,
)
from core.repositories.analytics_result_repository import (
    AnalyticsResultRepository,
    reset_in_memory_analytics_result_store,
)
from core.repositories.analytics_review_repository import (
    AnalyticsReviewRepository,
    reset_in_memory_analytics_review_store,
)
from core.repositories.conversation_repository import ConversationRepository, reset_in_memory_conversation_store
from core.repositories.data_source_repository import DataSourceRepository, reset_in_memory_data_source_store
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
    """重置性能验收使用的全部内存状态。"""

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_analytics_export_store()
    reset_in_memory_analytics_review_store()
    reset_in_memory_data_source_store()
    reset_in_memory_analytics_result_store()
    reset_async_task_runner()
    reset_global_cache()
    yield
    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()
    reset_in_memory_sql_audit_store()
    reset_in_memory_analytics_export_store()
    reset_in_memory_analytics_review_store()
    reset_in_memory_data_source_store()
    reset_in_memory_analytics_result_store()
    reset_async_task_runner()
    reset_global_cache()


def build_user_context(
    user_id: int = 1801,
    *,
    permissions: list[str] | None = None,
    roles: list[str] | None = None,
) -> UserContext:
    """构造最小经营分析用户上下文。"""

    return UserContext(
        user_id=user_id,
        username=f"user_{user_id}",
        display_name=f"user_{user_id}",
        roles=roles or ["employee", "analyst"],
        department_code="analytics-center",
        permissions=permissions
        or [
            "analytics:query",
            "analytics:review",
            "analytics:metric:generation",
            "analytics:metric:revenue",
            "analytics:metric:cost",
            "analytics:metric:profit",
            "analytics:metric:output",
        ],
    )


def build_services(
    tmp_path: Path,
) -> tuple[
    AnalyticsService,
    AnalyticsExportService,
    AnalyticsReviewService,
    TaskRunRepository,
    AnalyticsResultRepository,
    DataSourceRegistry,
]:
    """构造共享仓储的 analytics / export / review 服务集合。

    这里显式把 DataSourceRegistry 和 AnalyticsResultRepository 注入 service，
    目的是让验收测试能直接验证：
    - registry/cache 是否复用；
    - heavy result 是否已拆出 task_run.output_snapshot。
    """

    settings = Settings(
        local_export_dir=str(tmp_path),
        analytics_report_gateway_transport_mode="inprocess_report_mcp_server",
    )
    schema_registry = SchemaRegistry(settings=settings)
    data_source_repository = DataSourceRepository(session=None)
    data_source_registry = DataSourceRegistry(
        schema_registry=schema_registry,
        data_source_repository=data_source_repository,
    )
    metric_catalog = MetricCatalog(
        default_data_source=schema_registry.get_default_data_source().key,
        default_table_name=schema_registry.get_default_data_source().default_table,
    )
    conversation_repository = ConversationRepository(session=None)
    task_run_repository = TaskRunRepository(session=None)
    analytics_result_repository = AnalyticsResultRepository(session=None)
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
        data_source_registry=data_source_registry,
        analytics_result_repository=analytics_result_repository,
    )
    export_service = AnalyticsExportService(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
        analytics_export_repository=export_repository,
        analytics_review_repository=review_repository,
        report_gateway=ReportGateway(settings=settings),
        review_policy=review_policy,
        data_source_registry=data_source_registry,
        analytics_result_repository=analytics_result_repository,
    )
    review_service = AnalyticsReviewService(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
        analytics_export_repository=export_repository,
        analytics_review_repository=review_repository,
        analytics_export_service=export_service,
    )
    return (
        analytics_service,
        export_service,
        review_service,
        task_run_repository,
        analytics_result_repository,
        data_source_registry,
    )


def _estimate_json_size_bytes(payload: dict) -> int:
    """粗粒度估算 JSON 体量。

    这里不做网络层 gzip 估算，只看 Python 侧最终响应体的原始 JSON 大小，
    用于验证 lite / standard / full 分级是否真实减重。
    """

    return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))


def _wait_for_export_status(
    export_service: AnalyticsExportService,
    *,
    export_id: str,
    user_context: UserContext,
    timeout_seconds: float = 2.0,
) -> dict:
    """轮询等待导出任务到达终态。"""

    deadline = time.time() + timeout_seconds
    last_detail: dict | None = None
    while time.time() < deadline:
        last_detail = export_service.get_export_detail(
            export_id=export_id,
            user_context=user_context,
        )
        if last_detail["data"]["status"] in {"succeeded", "failed"}:
            return last_detail
        time.sleep(0.05)
    assert last_detail is not None
    return last_detail


def test_analytics_perf_acceptance_query_tiering_and_result_compaction(tmp_path: Path) -> None:
    """验收 query 分级、轻快照瘦身、重结果拆分和 timing_breakdown。

    该测试对应本轮最核心的 4 个验收点：
    1. lite / standard / full 的返回体量确实有层级差异；
    2. output_snapshot 不再膨胀到塞满重内容；
    3. tables / insight_cards / report_blocks / chart_spec 已拆到独立结果仓储；
    4. timing_breakdown 足以支撑最小慢点复盘。
    """

    (
        analytics_service,
        _export_service,
        _review_service,
        task_run_repository,
        analytics_result_repository,
        _data_source_registry,
    ) = build_services(tmp_path)
    user_context = build_user_context()

    mode_results: dict[str, dict] = {}
    perf_rows: list[dict] = []
    query = "帮我分析一下上个月新疆区域发电量"

    for mode in ("lite", "standard", "full"):
        started_at = time.perf_counter()
        result = analytics_service.submit_query(
            query=query,
            conversation_id=None,
            output_mode=mode,
            need_sql_explain=False,
            user_context=user_context,
        )
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        payload_size = _estimate_json_size_bytes(result["data"])
        mode_results[mode] = result
        perf_rows.append(
            {
                "mode": mode,
                "elapsed_ms": elapsed_ms,
                "payload_size": payload_size,
                "has_chart": "chart_spec" in result["data"],
                "has_insight": "insight_cards" in result["data"],
                "has_tables": "tables" in result["data"],
                "has_report": "report_blocks" in result["data"],
            }
        )

    lite_data = mode_results["lite"]["data"]
    standard_data = mode_results["standard"]["data"]
    full_data = mode_results["full"]["data"]

    assert "chart_spec" not in lite_data
    assert "insight_cards" not in lite_data
    assert "tables" not in lite_data
    assert "report_blocks" not in lite_data

    assert "chart_spec" in standard_data
    assert "insight_cards" in standard_data
    assert "tables" not in standard_data
    assert "report_blocks" not in standard_data

    assert "chart_spec" in full_data
    assert "insight_cards" in full_data
    assert "tables" in full_data
    assert "report_blocks" in full_data

    assert perf_rows[0]["payload_size"] < perf_rows[1]["payload_size"] < perf_rows[2]["payload_size"]

    full_run_id = mode_results["full"]["meta"]["run_id"]
    task_run = task_run_repository.get_task_run(full_run_id)
    assert task_run is not None
    output_snapshot = task_run["output_snapshot"]

    assert "tables" not in output_snapshot
    assert "insight_cards" not in output_snapshot
    assert "report_blocks" not in output_snapshot
    assert "chart_spec" not in output_snapshot
    assert output_snapshot["has_heavy_result"] is True

    heavy_result = analytics_result_repository.get_heavy_result(full_run_id)
    assert heavy_result is not None
    assert heavy_result["tables"]
    assert heavy_result["insight_cards"]
    assert heavy_result["report_blocks"]
    assert heavy_result["chart_spec"] is not None

    timing = output_snapshot["timing_breakdown"]
    required_keys = {
        "sql_build_ms",
        "sql_guard_ms",
        "sql_execute_ms",
        "masking_ms",
        "insight_ms",
        "report_ms",
    }
    assert required_keys.issubset(timing.keys())

    sorted_timing = sorted(timing.items(), key=lambda item: item[1], reverse=True)
    slowest_stage, slowest_cost = sorted_timing[0]
    top3_stages = sorted_timing[:3]
    assert slowest_stage in required_keys
    assert slowest_cost >= 0

    perf_table = [
        "| mode | elapsed_ms | payload_bytes | chart_spec | insight_cards | tables | report_blocks |",
        "| --- | ---: | ---: | --- | --- | --- | --- |",
    ]
    for row in perf_rows:
        perf_table.append(
            f"| {row['mode']} | {row['elapsed_ms']} | {row['payload_size']} | "
            f"{'Y' if row['has_chart'] else 'N'} | {'Y' if row['has_insight'] else 'N'} | "
            f"{'Y' if row['has_tables'] else 'N'} | {'Y' if row['has_report'] else 'N'} |"
        )

    print("\n[ANALYTICS PERF ACCEPTANCE]\n" + "\n".join(perf_table))
    print(
        "[ANALYTICS PERF SUMMARY] "
        f"snapshot_slimmed={'Y' if output_snapshot.get('has_heavy_result') else 'N'}, "
        f"heavy_result_split={'Y' if heavy_result else 'N'}, "
        f"slowest_stage={slowest_stage}, "
        f"slowest_cost_ms={slowest_cost}"
    )
    print(
        "[ANALYTICS PERF TOP3] "
        + ", ".join(f"{stage}={cost}ms" for stage, cost in top3_stages)
    )


def test_analytics_perf_acceptance_export_async_review_and_cache(tmp_path: Path) -> None:
    """验收 export 异步语义、review 串联和 registry 缓存复用。

    该测试把剩余几个性能验收点合在一起：
    1. POST export 后不再同步等待最终导出；
    2. review 通过后导出会继续异步执行；
    3. DataSourceRegistry 高频读取时缓存会复用，而不是每次重新构造。
    """

    (
        analytics_service,
        export_service,
        review_service,
        _task_run_repository,
        _analytics_result_repository,
        data_source_registry,
    ) = build_services(tmp_path)
    owner_context = build_user_context(user_id=1802)
    reviewer_context = build_user_context(
        user_id=2802,
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

    # 先验证 registry/schema 高频读取的缓存复用。
    cache = get_global_cache()
    initial_size = cache.size()
    first_sources = data_source_registry.list_data_sources()
    size_after_first = cache.size()
    second_sources = data_source_registry.list_data_sources()
    size_after_second = cache.size()
    first_default = data_source_registry.get_data_source("local_analytics")
    size_after_get_first = cache.size()
    second_default = data_source_registry.get_data_source("local_analytics")
    size_after_get_second = cache.size()

    assert first_sources == second_sources
    assert first_default.key == second_default.key == "local_analytics"
    assert size_after_first >= initial_size
    assert size_after_second == size_after_first
    assert size_after_get_second == size_after_get_first

    normal_run = analytics_service.submit_query(
        query="帮我分析一下上个月新疆区域发电量",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=owner_context,
    )

    normal_export = export_service.create_export(
        run_id=normal_run["meta"]["run_id"],
        export_type="markdown",
        export_template="weekly_report",
        user_context=owner_context,
    )

    assert normal_export["meta"]["status"] == "pending"
    assert normal_export["data"]["filename"] is None
    assert normal_export["data"]["artifact_path"] is None
    normal_detail = _wait_for_export_status(
        export_service,
        export_id=normal_export["data"]["export_id"],
        user_context=owner_context,
    )
    assert normal_detail["data"]["status"] == "succeeded"
    assert normal_detail["data"]["metadata"]["export_render_ms"] >= 0

    high_risk_run = analytics_service.submit_query(
        query="帮我分析一下上个月新疆区域收入",
        conversation_id=None,
        output_mode="full",
        need_sql_explain=False,
        user_context=owner_context,
    )
    review_export = export_service.create_export(
        run_id=high_risk_run["meta"]["run_id"],
        export_type="pdf",
        export_template="monthly_report",
        user_context=owner_context,
    )

    assert review_export["meta"]["status"] == "awaiting_human_review"
    assert review_export["data"]["review_required"] is True
    assert review_export["data"]["review_status"] == "pending"

    approved = review_service.approve_review(
        review_id=review_export["data"]["review_id"],
        comment="性能验收场景下允许继续导出。",
        reviewer_context=reviewer_context,
    )
    assert approved["data"]["review"]["review_status"] == "approved"
    assert approved["data"]["export"]["status"] in {"pending", "running", "succeeded"}

    reviewed_detail = _wait_for_export_status(
        export_service,
        export_id=review_export["data"]["export_id"],
        user_context=owner_context,
    )
    assert reviewed_detail["data"]["status"] == "succeeded"

    print(
        "\n[ANALYTICS PERF CACHE] "
        f"cache_size_before={initial_size}, "
        f"after_first_list={size_after_first}, "
        f"after_second_list={size_after_second}, "
        f"after_get={size_after_get_second}"
    )
    print(
        "[ANALYTICS PERF EXPORT] "
        f"normal_export_async={'Y' if normal_export['meta']['status'] == 'pending' else 'N'}, "
        f"review_export_async={'Y' if review_export['meta']['status'] == 'awaiting_human_review' else 'N'}, "
        f"reviewed_export_final={reviewed_detail['data']['status']}"
    )
