"""经营分析性能测试。

这些测试用于验证经营分析链路的性能特征：
1. 意图解析延迟
2. SQL 构建延迟
3. 端到端延迟
4. 并发处理能力
"""

from __future__ import annotations

import time
import pytest
from unittest.mock import MagicMock

from core.analytics.intent.parser import LLMAnalyticsIntentParser
from core.analytics.intent.validator import AnalyticsIntentValidator
from core.analytics.intent.schema import (
    AnalyticsIntent,
    MetricIntent,
    TimeRangeIntent,
    IntentConfidence,
    ComplexityType,
    PlanningMode,
    AnalysisIntentType,
    TimeRangeType,
    CompareTarget,
)
from core.agent.control_plane.intent_sql_builder import AnalyticsIntentSQLBuilder
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.config.settings import Settings


# ============================================================================
# Intent Parser 性能测试
# ============================================================================

def test_intent_parser_latency():
    """测试意图解析延迟。"""

    parser = LLMAnalyticsIntentParser(settings=Settings())
    validator = AnalyticsIntentValidator()

    queries = [
        "查询新疆区域2024年3月发电量",
        "帮我看一下上个月各电站的发电量情况",
        "分析一下近三个月各区域的收入变化",
        "发电量怎么样",
    ]

    latencies = []
    for query in queries:
        start = time.time()
        result = parser.parse(query=query)
        latency = time.time() - start
        latencies.append(latency)

    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)

    # 意图解析应该在 100ms 内完成（假设 mock LLM 响应很快）
    # 实际场景中会有 LLM 调用延迟
    print(f"\n意图解析延迟: avg={avg_latency*1000:.2f}ms, max={max_latency*1000:.2f}ms")
    assert avg_latency < 1.0  # 小于 1 秒


# ============================================================================
# Intent Validator 性能测试
# ============================================================================

def test_validator_latency():
    """测试意图校验延迟。"""

    validator = AnalyticsIntentValidator()

    intent = AnalyticsIntent(
        task_type="analytics_query",
        complexity=ComplexityType.SIMPLE,
        planning_mode=PlanningMode.DIRECT,
        analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
        metric=MetricIntent(
            raw_text="发电量",
            metric_code="generation",
            metric_name="发电量",
            confidence=0.9,
        ),
        time_range=TimeRangeIntent(
            raw_text="2024-03",
            type=TimeRangeType.ABSOLUTE,
            value="2024-03",
            start="2024-03-01",
            end="2024-03-31",
            confidence=0.9,
        ),
        confidence=IntentConfidence(overall=0.9),
        need_clarification=False,
        missing_fields=[],
        ambiguous_fields=[],
    )

    start = time.time()
    result = validator.validate(intent)
    latency = time.time() - start

    print(f"\n意图校验延迟: {latency*1000:.2f}ms")
    # 校验是纯本地计算，应该非常快
    assert latency < 0.05  # 小于 50ms


# ============================================================================
# SQL Builder 性能测试
# ============================================================================

def test_sql_builder_direct_mode_latency():
    """测试 Direct 模式 SQL 构建延迟。"""

    schema_registry = SchemaRegistry()
    metric_catalog = MetricCatalog(
        default_data_source=schema_registry.get_default_data_source().key,
        default_table_name=schema_registry.get_default_data_source().default_table,
    )
    builder = AnalyticsIntentSQLBuilder(
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )

    intent = AnalyticsIntent(
        task_type="analytics_query",
        complexity=ComplexityType.SIMPLE,
        planning_mode=PlanningMode.DIRECT,
        analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
        metric=MetricIntent(
            raw_text="发电量",
            metric_code="generation",
            metric_name="发电量",
            confidence=0.9,
        ),
        time_range=TimeRangeIntent(
            raw_text="2024-03",
            type=TimeRangeType.ABSOLUTE,
            value="2024-03",
            start="2024-03-01",
            end="2024-03-31",
            confidence=0.9,
        ),
        confidence=IntentConfidence(overall=0.9),
        need_clarification=False,
        missing_fields=[],
        ambiguous_fields=[],
    )

    start = time.time()
    sql_bundle = builder.build(intent, department_code="analytics-center")
    latency = time.time() - start

    print(f"\nDirect 模式 SQL 构建延迟: {latency*1000:.2f}ms")
    assert latency < 0.1  # 小于 100ms
    assert "generated_sql" in sql_bundle


def test_sql_builder_complex_mode_latency():
    """测试 Complex 模式 SQL 构建延迟。"""

    from core.analytics.intent.schema import RequiredQueryIntent, PeriodRole

    schema_registry = SchemaRegistry()
    metric_catalog = MetricCatalog(
        default_data_source=schema_registry.get_default_data_source().key,
        default_table_name=schema_registry.get_default_data_source().default_table,
    )
    builder = AnalyticsIntentSQLBuilder(
        schema_registry=schema_registry,
        metric_catalog=metric_catalog,
    )

    intent = AnalyticsIntent(
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
        compare_target=CompareTarget.NONE,
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

    start = time.time()
    sql_bundle = builder.build(intent, department_code="analytics-center")
    latency = time.time() - start

    print(f"\nComplex 模式 SQL 构建延迟: {latency*1000:.2f}ms")
    # 复杂模式可能需要生成多个子查询，稍慢
    assert latency < 0.2  # 小于 200ms
    assert "sub_queries" in sql_bundle or "generated_sql" in sql_bundle


# ============================================================================
# 吞吐量测试
# ============================================================================

def test_intent_parsing_throughput():
    """测试意图解析吞吐量。"""

    parser = LLMAnalyticsIntentParser(settings=Settings())
    validator = AnalyticsIntentValidator()

    queries = [
        "查询新疆区域2024年3月发电量",
        "帮我看一下上个月各电站的发电量情况",
        "分析一下近三个月各区域的收入变化",
        "发电量怎么样",
        "成本情况如何",
        "利润分析一下",
    ] * 10  # 60 个查询

    start = time.time()
    for query in queries:
        result = parser.parse(query=query)
    total_time = time.time() - start

    throughput = len(queries) / total_time

    print(f"\n意图解析吞吐量: {throughput:.2f} queries/sec")
    # 吞吐量应该足够处理日常查询
    assert throughput > 10  # 每秒至少 10 个查询


# ============================================================================
# 内存使用测试
# ============================================================================

def test_intent_memory_usage():
    """测试意图对象的内存占用。"""

    import sys

    intent = AnalyticsIntent(
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
        compare_target=CompareTarget.NONE,
        confidence=IntentConfidence(overall=0.92),
        need_clarification=False,
        missing_fields=[],
        ambiguous_fields=[],
    )

    size = sys.getsizeof(intent)
    print(f"\n意图对象内存占用: {size} bytes")

    # 意图对象应该很小
    assert size < 10000  # 小于 10KB


# ============================================================================
# 并发测试
# ============================================================================

def test_concurrent_intent_parsing():
    """测试并发意图解析。"""

    import concurrent.futures

    parser = LLMAnalyticsIntentParser(settings=Settings())

    def parse_query(query: str):
        start = time.time()
        result = parser.parse(query=query)
        return time.time() - start

    queries = [
        "查询新疆区域2024年3月发电量",
        "帮我看一下上个月各电站的发电量情况",
        "分析一下近三个月各区域的收入变化",
        "发电量怎么样",
    ] * 25  # 100 个查询

    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(parse_query, q) for q in queries]
        latencies = [f.result() for f in concurrent.futures.as_completed(futures)]
    total_time = time.time() - start

    avg_latency = sum(latencies) / len(latencies)
    throughput = len(queries) / total_time

    print(f"\n并发意图解析: avg={avg_latency*1000:.2f}ms, throughput={throughput:.2f} queries/sec")
    # 并发应该能提高吞吐量
    assert throughput > 50  # 每秒至少 50 个查询
