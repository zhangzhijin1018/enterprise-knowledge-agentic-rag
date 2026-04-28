"""Schema Registry / Metric Catalog 测试。"""

from __future__ import annotations

from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry


def test_metric_catalog_resolves_metric_alias() -> None:
    """指标目录应支持指标别名映射。"""

    catalog = MetricCatalog()

    metric_definition = catalog.resolve_metric("营收")

    assert metric_definition is not None
    assert metric_definition.name == "收入"
    assert metric_definition.metric_code == "revenue"


def test_schema_registry_returns_group_by_rule() -> None:
    """Schema Registry 应能返回 group_by 规则。"""

    registry = SchemaRegistry()

    rule = registry.get_group_by_rule("station", data_source="local_analytics")

    assert rule is not None
    assert rule.alias == "station"
    assert "station_name" in rule.select_expression
