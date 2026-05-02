"""经营分析意图解析模块。

核心组件：
- AnalyticsIntent：统一意图结构
- LLMAnalyticsIntentParser：LLM 统一解析器
- QueryPlanner：子查询规划器（支持 SINGLE/PARALLEL/JOIN 策略）
- QueryExecutor：查询执行器（支持并行执行）
- ClarificationManager：歧义检测与澄清管理器

执行策略：
- SINGLE：单个查询，直接执行
- PARALLEL：同一数据源 + 同表 + 不同时间 → 并行查询
- JOIN：同一数据源 + 多表 → SQL JOIN
"""

from core.analytics.intent.clarification_manager import (
    ClarificationContext,
    ClarificationManager,
    detect_and_clarify,
)
from core.analytics.intent.parser import (
    IntentParserOutputValidator,
    IntentParserResult,
    LLMAnalyticsIntentParser,
)
from core.analytics.intent.query_executor import (
    ExecutionResult,
    QueryExecutor,
    QueryResult,
    execute_plan,
)
from core.analytics.intent.query_planner import (
    PlanningContext,
    QueryPlanner,
    create_required_query,
)
from core.analytics.intent.schema import (
    AnalyticsIntent,
    AnalysisIntentType,
    ClarificationOption,
    ClarificationResponse,
    ClarificationType,
    CompareTarget,
    ComplexityType,
    ExecutionPhase,
    ExecutionPlan,
    ExecutionStrategy,
    IntentConfidence,
    MetricCandidate,
    MetricIntent,
    OrgCandidate,
    OrgScopeIntent,
    OrgScopeType,
    PeriodRole,
    PlanningMode,
    RequiredQuery,
    TimeRangeIntent,
    TimeRangeType,
)
from core.analytics.intent.validator import AnalyticsIntentValidator, IntentValidationResult

__all__ = [
    # 核心意图结构
    "AnalyticsIntent",
    "AnalyticsIntentValidator",
    "AnalysisIntentType",
    "ClarificationOption",
    "ClarificationResponse",
    "ClarificationType",
    "CompareTarget",
    "ComplexityType",
    "ExecutionPhase",
    "ExecutionPlan",
    "ExecutionStrategy",
    "IntentConfidence",
    "IntentParserOutputValidator",
    "IntentParserResult",
    "LLMAnalyticsIntentParser",
    "MetricCandidate",
    "MetricIntent",
    "OrgCandidate",
    "OrgScopeIntent",
    "OrgScopeType",
    "PeriodRole",
    "PlanningMode",
    "RequiredQuery",
    "TimeRangeIntent",
    "TimeRangeType",
    "IntentValidationResult",
    # 解析器与校验器
    "QueryPlanner",
    "PlanningContext",
    "create_required_query",
    # 执行器
    "QueryExecutor",
    "ExecutionResult",
    "QueryResult",
    "execute_plan",
    # 澄清管理器
    "ClarificationManager",
    "ClarificationContext",
    "detect_and_clarify",
]
