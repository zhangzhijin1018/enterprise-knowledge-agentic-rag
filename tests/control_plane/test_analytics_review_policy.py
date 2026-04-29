"""经营分析 Human Review 策略测试。"""

from __future__ import annotations

from core.agent.control_plane.analytics_review_policy import AnalyticsReviewPolicy
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry


def test_review_policy_does_not_trigger_for_normal_markdown_export() -> None:
    """普通 markdown 导出不应默认触发审核。"""

    registry = SchemaRegistry()
    catalog = MetricCatalog(
        default_data_source=registry.get_default_data_source().key,
        default_table_name=registry.get_default_data_source().default_table,
    )
    policy = AnalyticsReviewPolicy(high_row_count_threshold=100)

    decision = policy.evaluate_export(
        export_type="markdown",
        output_snapshot={
            "row_count": 3,
            "masked_fields": [],
            "governance_decision": {"sensitive_fields": []},
        },
        metric_definition=catalog.resolve_metric("发电量"),
        data_source_definition=registry.get_data_source("local_analytics"),
    )

    assert decision.review_required is False
    assert decision.review_level == "not_required"


def test_review_policy_triggers_for_formal_export_and_sensitive_metric() -> None:
    """正式导出或高敏指标应触发审核。"""

    registry = SchemaRegistry()
    catalog = MetricCatalog(
        default_data_source=registry.get_default_data_source().key,
        default_table_name=registry.get_default_data_source().default_table,
    )
    policy = AnalyticsReviewPolicy(high_row_count_threshold=100)

    decision = policy.evaluate_export(
        export_type="pdf",
        output_snapshot={
            "row_count": 6,
            "masked_fields": [],
            "governance_decision": {"sensitive_fields": []},
        },
        metric_definition=catalog.resolve_metric("收入"),
        data_source_definition=registry.get_data_source("local_analytics"),
    )

    assert decision.review_required is True
    assert decision.review_level == "high"
    assert "正式导出类型需要人工复核" in (decision.review_reason or "")
