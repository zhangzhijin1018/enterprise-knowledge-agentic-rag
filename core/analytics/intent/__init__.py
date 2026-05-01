"""AnalyticsIntent 模块。

导出统一的 Intent 模型和解析器。
"""

from core.analytics.intent.schema import (
    AnalyticsIntent,
    AnalyticsIntentComplexity,
    AnalyticsIntentPlanningMode,
    AnalysisIntentType,
    CompareTarget,
    IntentConfidence,
    IntentValidationResult,
    MetricCandidate,
    MetricIntent,
    OrgCandidate,
    OrgScopeIntent,
    OrgScopeType,
    PeriodRole,
    SortDirection,
    TimeRangeIntent,
    TimeRangeType,
)

# 为向后兼容保留 RequiredQueryIntent 作为 AnalyticsIntent 的别名
RequiredQueryIntent = AnalyticsIntent

__all__ = [
    "AnalyticsIntent",
    "AnalyticsIntentComplexity",
    "AnalyticsIntentPlanningMode",
    "AnalysisIntentType",
    "CompareTarget",
    "IntentConfidence",
    "IntentValidationResult",
    "MetricCandidate",
    "MetricIntent",
    "OrgCandidate",
    "OrgScopeIntent",
    "OrgScopeType",
    "PeriodRole",
    "RequiredQueryIntent",
    "SortDirection",
    "TimeRangeIntent",
    "TimeRangeType",
]
