"""SQL Builder 测试。"""

from __future__ import annotations

from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.agent.control_plane.sql_builder import SQLBuilder


def test_sql_builder_generates_schema_aware_sql() -> None:
    """Schema-aware SQL Builder 应根据目录定义生成目标 SQL。"""

    builder = SQLBuilder(
        schema_registry=SchemaRegistry(),
        metric_catalog=MetricCatalog(),
    )

    result = builder.build(
        {
            "metric": "发电量",
            "time_range": {
                "label": "上个月",
                "start_date": "2024-03-01",
                "end_date": "2024-03-31",
            },
            "org_scope": {"type": "region", "value": "新疆区域"},
            "group_by": "station",
            "compare_target": "mom",
        },
        department_code="analytics-center",
    )

    assert result["data_source"] == "local_analytics"
    assert "analytics_metrics_daily" in result["generated_sql"]
    assert "metric_code = 'generation'" in result["generated_sql"]
    assert "region_name = '新疆区域'" in result["generated_sql"]
    assert "department_code = 'analytics-center'" in result["generated_sql"]
    assert "station_name AS station" in result["generated_sql"]


def test_sql_builder_generates_compare_sql() -> None:
    """compare_target = mom 时应生成受控 compare SQL。"""

    builder = SQLBuilder(
        schema_registry=SchemaRegistry(),
        metric_catalog=MetricCatalog(),
    )

    result = builder.build(
        {
            "metric": "发电量",
            "time_range": {
                "label": "本月",
                "start_date": "2024-04-01",
                "end_date": "2024-04-30",
            },
            "compare_target": "mom",
        },
        department_code="analytics-center",
    )

    assert "CASE" in result["generated_sql"]
    assert "current_value" in result["generated_sql"]
    assert "compare_value" in result["generated_sql"]


def test_sql_builder_generates_topn_sql() -> None:
    """topN 场景应生成带排序和 LIMIT 的受控 SQL。"""

    builder = SQLBuilder(
        schema_registry=SchemaRegistry(),
        metric_catalog=MetricCatalog(),
    )

    result = builder.build(
        {
            "metric": "发电量",
            "time_range": {
                "label": "上个月",
                "start_date": "2024-03-01",
                "end_date": "2024-03-31",
            },
            "group_by": "station",
            "top_n": 5,
            "sort_direction": "asc",
        },
        department_code="analytics-center",
    )

    assert "ORDER BY total_value ASC" in result["generated_sql"]
    assert result["generated_sql"].endswith("LIMIT 5")


def test_sql_builder_generates_month_trend_sql() -> None:
    """按月趋势场景应生成 month 分组 SQL。"""

    builder = SQLBuilder(
        schema_registry=SchemaRegistry(),
        metric_catalog=MetricCatalog(),
    )

    result = builder.build(
        {
            "metric": "收入",
            "time_range": {
                "label": "上个月",
                "start_date": "2024-03-01",
                "end_date": "2024-03-31",
            },
            "group_by": "month",
        },
        department_code="analytics-center",
    )

    assert "substr(biz_date, 1, 7) AS month" in result["generated_sql"]
    assert result["builder_metadata"]["sql_template_version"] == "analytics_v7"
