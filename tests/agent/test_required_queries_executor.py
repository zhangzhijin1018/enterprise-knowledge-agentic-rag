"""RequiredQueriesExecutor 单元测试。"""

from __future__ import annotations

import pytest

from unittest.mock import MagicMock, patch

from core.analytics.intent.schema import (
    AnalyticsIntent,
    MetricIntent,
    TimeRangeIntent,
    RequiredQueryIntent,
    IntentConfidence,
    ComplexityType,
    PlanningMode,
    AnalysisIntentType,
    TimeRangeType,
    PeriodRole,
)
from core.agent.control_plane.intent_sql_builder import AnalyticsIntentSQLBuilder
from core.agent.control_plane.sql_guard import SQLGuard
from core.agent.control_plane.required_queries_executor import (
    RequiredQueriesExecutor,
    QueryExecutionResult,
    CombinedExecutionResult,
)
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry


@pytest.fixture
def sql_builder() -> AnalyticsIntentSQLBuilder:
    """创建 SQL Builder。"""
    schema_registry = SchemaRegistry()
    metric_catalog = MetricCatalog(
        default_data_source=schema_registry.get_default_data_source().key,
        default_table_name=schema_registry.get_default_data_source().default_table,
    )
    return AnalyticsIntentSQLBuilder(
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )


@pytest.fixture
def sql_guard() -> SQLGuard:
    """创建 SQL Guard。"""
    return SQLGuard(allowed_tables=["analytics_metrics_daily"])


@pytest.fixture
def mock_gateway():
    """创建 Mock SQL Gateway。"""
    gateway = MagicMock()
    gateway.execute_readonly_query.return_value = MagicMock(
        rows=[
            {"region": "新疆", "total_value": 1000},
            {"region": "甘肃", "total_value": 800},
        ],
        columns=["region", "total_value"],
        row_count=2,
        latency_ms=50,
    )
    return gateway


@pytest.fixture
def executor(sql_builder, sql_guard, mock_gateway) -> RequiredQueriesExecutor:
    """创建 Executor。"""
    return RequiredQueriesExecutor(
        sql_builder=sql_builder,
        sql_guard=sql_guard,
        sql_gateway=mock_gateway,
    )


def create_complex_intent() -> AnalyticsIntent:
    """创建复杂意图。"""
    return AnalyticsIntent(
        task_type="analytics_query",
        complexity=ComplexityType.COMPLEX,
        planning_mode=PlanningMode.DECOMPOSED,
        analysis_intent=AnalysisIntentType.DECLINE_ATTRIBUTION,
        metric=MetricIntent(
            raw_text="发电量",
            metric_code="generation",
            metric_name="发电量",
            confidence=0.95,
        ),
        time_range=TimeRangeIntent(
            raw_text="近三个月",
            type=TimeRangeType.RELATIVE,
            value="近三个月",
            confidence=0.9,
        ),
        org_scope=None,
        group_by="region",
        compare_target=None,
        confidence=IntentConfidence(overall=0.92),
        need_clarification=False,
        missing_fields=[],
        ambiguous_fields=[],
        required_queries=[
            RequiredQueryIntent(
                query_name="current",
                purpose="查询当前周期",
                metric_code="generation",
                period_role=PeriodRole.CURRENT,
                group_by="region",
            ),
            RequiredQueryIntent(
                query_name="yoy_baseline",
                purpose="查询去年同期",
                metric_code="generation",
                period_role=PeriodRole.YOY_BASELINE,
                group_by="region",
            ),
        ],
    )


# ============================================================================
# 组合结果测试
# ============================================================================

def test_extract_key_from_row(executor: RequiredQueriesExecutor) -> None:
    """测试从行数据中提取键。"""
    row = {"region": "新疆", "station": "电站A", "total_value": 1000}
    columns = ["region", "station", "total_value"]

    key = executor._extract_key(row, columns)
    assert key == "新疆"


def test_extract_key_with_fallback(executor: RequiredQueriesExecutor) -> None:
    """测试键提取回退逻辑。"""
    row = {"total_value": 1000, "count": 5}
    columns = ["total_value", "count"]

    key = executor._extract_key(row, columns)
    assert key == ""


# ============================================================================
# 组合结果测试
# ============================================================================

def test_combine_results_no_baseline(executor: RequiredQueriesExecutor) -> None:
    """没有基准查询时直接返回主查询结果。"""
    main = QueryExecutionResult(
        query_name="current",
        period_role="current",
        rows=[{"region": "新疆", "value": 1000}],
        columns=["region", "value"],
        row_count=1,
        latency_ms=50,
    )

    result = executor._combine_results(main, [])
    assert len(result) == 1
    assert result[0]["region"] == "新疆"


def test_combine_results_with_baseline(executor: RequiredQueriesExecutor) -> None:
    """有基准查询时计算同比。"""
    main = QueryExecutionResult(
        query_name="current",
        period_role="current",
        rows=[{"region": "新疆", "total_value": 1200}],
        columns=["region", "total_value"],
        row_count=1,
        latency_ms=50,
    )
    baseline = QueryExecutionResult(
        query_name="yoy",
        period_role="yoy_baseline",
        rows=[{"region": "新疆", "total_value": 1000}],
        columns=["region", "total_value"],
        row_count=1,
        latency_ms=50,
    )

    result = executor._combine_results(main, [baseline])
    assert len(result) == 1
    assert result[0]["total_value"] == 1200
    assert result[0]["baseline_value"] == 1000
    assert result[0]["change_ratio"] == 0.2  # (1200-1000)/1000
    assert result[0]["change_value"] == 200


def test_combine_results_with_zero_baseline(executor: RequiredQueriesExecutor) -> None:
    """基准值为零时 change_ratio 为 None。"""
    main = QueryExecutionResult(
        query_name="current",
        period_role="current",
        rows=[{"region": "新疆", "total_value": 1200}],
        columns=["region", "total_value"],
        row_count=1,
        latency_ms=50,
    )
    baseline = QueryExecutionResult(
        query_name="yoy",
        period_role="yoy_baseline",
        rows=[{"region": "新疆", "total_value": 0}],
        columns=["region", "total_value"],
        row_count=1,
        latency_ms=50,
    )

    result = executor._combine_results(main, [baseline])
    assert len(result) == 1
    assert result[0]["change_ratio"] is None
    assert result[0]["change_value"] == 1200  # main - 0


# ============================================================================
# 摘要构建测试
# ============================================================================

def test_build_summary(executor: RequiredQueriesExecutor) -> None:
    """测试摘要构建。"""
    main = QueryExecutionResult(
        query_name="current",
        period_role="current",
        rows=[{"region": "新疆", "value": 1000}],
        columns=["region", "value"],
        row_count=1,
        latency_ms=50,
    )
    baseline = QueryExecutionResult(
        query_name="yoy",
        period_role="yoy_baseline",
        rows=[],
        columns=[],
        row_count=0,
        latency_ms=40,
    )

    result = CombinedExecutionResult(
        main_result=main,
        baseline_results=[baseline],
        combined_rows=[{"region": "新疆", "value": 1000}],
    )

    summary = executor._build_summary(result)

    assert summary["total_queries"] == 2
    assert summary["successful_queries"] == 2
    assert summary["main_query"]["rows"] == 1
    assert summary["main_query"]["latency_ms"] == 50
    assert len(summary["baseline_queries"]) == 1
