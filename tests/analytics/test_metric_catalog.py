"""MetricCatalog 治理测试。"""

from __future__ import annotations

from core.analytics.metric_catalog import MetricCatalog


def test_metric_catalog_resolves_alias_and_governance_metadata() -> None:
    """指标别名解析后应保留治理元数据。"""

    catalog = MetricCatalog()

    metric = catalog.resolve_metric("营收")

    assert metric is not None
    assert metric.name == "收入"
    assert metric.required_permissions
    assert metric.allowed_roles
    assert metric.allowed_departments
    assert metric.sensitivity_level == "restricted"


def test_metric_catalog_finds_generation_metric_in_query() -> None:
    """查询语句中的指标别名应能映射到标准指标。"""

    catalog = MetricCatalog()

    metric = catalog.find_metric_in_query("最近发电表现怎么样")

    assert metric is not None
    assert metric.name == "发电量"
