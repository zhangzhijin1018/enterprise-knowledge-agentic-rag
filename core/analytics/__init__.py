"""经营分析模块包。

该目录未来用于承载 SQL 分析、结果解释和经营报告能力。
"""

from core.analytics.insight_builder import InsightBuilder
from core.analytics.metric_catalog import MetricCatalog, MetricDefinition
from core.analytics.report_formatter import ReportFormatter
from core.analytics.schema_registry import DataSourceDefinition, GroupByRule, SchemaRegistry, TableDefinition

__all__ = [
    "InsightBuilder",
    "MetricCatalog",
    "MetricDefinition",
    "ReportFormatter",
    "SchemaRegistry",
    "GroupByRule",
    "TableDefinition",
    "DataSourceDefinition",
]
