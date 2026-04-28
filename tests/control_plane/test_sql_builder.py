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
        }
    )

    assert result["data_source"] == "local_analytics"
    assert "analytics_metrics_daily" in result["generated_sql"]
    assert "metric_code = 'generation'" in result["generated_sql"]
    assert "region_name = '新疆区域'" in result["generated_sql"]
    assert "station_name AS station" in result["generated_sql"]
