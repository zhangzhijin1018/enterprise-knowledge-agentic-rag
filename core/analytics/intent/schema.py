"""经营分析统一意图结构（AnalyticsIntent）。

核心设计理念：
1. 所有用户问句统一由 LLM 生成结构化 AnalyticsIntent；
2. 意图结构包含语义理解、指标选择、子查询规划等完整信息；
3. 支持复杂归因分析、跨数据源查询、多子查询并行/串行执行；
4. 本地层负责歧义检测、执行规划，不做语义理解。

执行策略：
- 同一数据源 + 多表：SQL JOIN（最优）
- 同一数据源 + 同表：并行查询 → 应用层合并
- 不同数据源：并行查询 → 应用层合并
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# 枚举类型定义
# =============================================================================


class ComplexityType(str, Enum):
    """问题复杂度枚举。"""

    SIMPLE = "simple"  # 简单查询，单次 SQL 即可完成
    COMPLEX = "complex"  # 复杂查询，需要拆解为多个子查询


class PlanningMode(str, Enum):
    """规划模式枚举。"""

    DIRECT = "direct"  # 直接执行，无需拆解
    DECOMPOSED = "decomposed"  # 需要拆解为多个子查询
    CLARIFICATION = "clarification"  # 需要用户澄清
    RULE_FALLBACK = "rule_fallback"  # 规则 Planner 回退


class AnalysisIntentType(str, Enum):
    """分析意图类型枚举。"""

    SIMPLE_QUERY = "simple_query"  # 简单查询，直接返回数据
    TREND_ANALYSIS = "trend_analysis"  # 趋势分析
    RANKING = "ranking"  # 排名分析
    DECLINE_ATTRIBUTION = "decline_attribution"  # 下降归因
    COMPARISON = "comparison"  # 对比分析
    REPORT_GENERATION = "report_generation"  # 报告生成


class CompareTarget(str, Enum):
    """对比目标枚举。"""

    NONE = "none"
    YOY = "yoy"  # 同比
    MOM = "mom"  # 环比


class TimeRangeType(str, Enum):
    """时间范围类型枚举。"""

    ABSOLUTE = "absolute"  # 绝对时间（如 2024-03）
    RELATIVE = "relative"  # 相对时间（如 最近三个月）


class OrgScopeType(str, Enum):
    """组织范围类型枚举。"""

    REGION = "region"
    STATION = "station"
    DEPARTMENT = "department"
    GROUP = "group"


class PeriodRole(str, Enum):
    """子查询周期角色枚举。"""

    CURRENT = "current"  # 当前周期
    YOY_BASELINE = "yoy_baseline"  # 同比基准（去年同期）
    MOM_BASELINE = "mom_baseline"  # 环比基准（上个月）


class ExecutionStrategy(str, Enum):
    """执行策略枚举。

    定义了同一数据源内多个查询的执行策略：
    - single：单个查询，无需特殊处理
    - parallel：并行查询（同一数据源、同表但不同时间周期）
    - join：SQL JOIN（同一数据源、多表关联查询）
    """

    SINGLE = "single"  # 单个查询
    PARALLEL = "parallel"  # 并行查询
    JOIN = "join"  # SQL JOIN


class ClarificationType(str, Enum):
    """澄清类型枚举。"""

    METRIC_AMBIGUITY = "metric_ambiguity"  # 指标歧义
    METRIC_MISSING = "metric_missing"  # 指标缺失
    TIME_RANGE_MISSING = "time_range_missing"  # 时间范围缺失
    ORG_SCOPE_MISSING = "org_scope_missing"  # 组织范围缺失


# =============================================================================
# 内部结构定义
# =============================================================================


class MetricCandidate(BaseModel):
    """指标候选对象。

    当用户输入存在歧义时，提供多个可能的指标候选。
    """

    metric_code: str = Field(description="指标代码")
    metric_name: str = Field(description="指标名称")
    confidence: float = Field(description="候选置信度，0-1", ge=0.0, le=1.0)
    business_domain: str | None = Field(default=None, description="业务域")


class MetricIntent(BaseModel):
    """指标意图结构。"""

    raw_text: str | None = Field(default=None, description="用户原始指标文本")
    metric_code: str | None = Field(default=None, description="解析后的指标代码")
    metric_name: str | None = Field(default=None, description="解析后的指标名称")
    confidence: float = Field(description="指标解析置信度，0-1", ge=0.0, le=1.0)
    candidates: list[MetricCandidate] = Field(default_factory=list, description="指标候选列表（当存在歧义时）")

    @field_validator("metric_code", "metric_name", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip()
        return v


class TimeRangeIntent(BaseModel):
    """时间范围意图结构。"""

    raw_text: str | None = Field(default=None, description="用户原始时间文本")
    type: TimeRangeType = Field(description="时间范围类型")
    value: str | None = Field(default=None, description="时间范围值")
    start: str | None = Field(default=None, description="绝对时间范围起始日期")
    end: str | None = Field(default=None, description="绝对时间范围结束日期")
    relative_periods: list[str] | None = Field(default=None, description="相对时间周期列表（如 ['最近3个月', '上月']）")
    confidence: float = Field(description="时间范围解析置信度，0-1", ge=0.0, le=1.0)


class OrgCandidate(BaseModel):
    """组织候选对象。"""

    type: str = Field(description="组织类型")
    name: str = Field(description="组织名称")
    code: str | None = Field(default=None, description="组织代码")
    confidence: float = Field(description="候选置信度，0-1", ge=0.0, le=1.0)


class OrgScopeIntent(BaseModel):
    """组织范围意图结构。"""

    raw_text: str | None = Field(default=None, description="用户原始组织范围文本")
    type: OrgScopeType | None = Field(default=None, description="组织范围类型")
    name: str | None = Field(default=None, description="组织范围名称")
    code: str | None = Field(default=None, description="组织范围代码")
    confidence: float = Field(description="组织范围解析置信度，0-1", ge=0.0, le=1.0)
    candidates: list[OrgCandidate] = Field(default_factory=list, description="组织候选列表")


class RequiredQuery(BaseModel):
    """必需子查询结构。

    用于 complex 查询中拆解的多个子查询。
    每个子查询对应一个具体的数据源和指标。
    """

    query_id: str = Field(description="子查询唯一标识")
    query_name: str = Field(description="子查询名称（如 current、yoy_baseline）")
    purpose: str = Field(description="子查询目的说明")

    # 指标信息
    metric_code: str | None = Field(default=None, description="该子查询使用的指标代码")
    metric_name: str | None = Field(default=None, description="该子查询使用的指标名称")

    # 数据源信息（由 QueryPlanner 填充）
    data_source_key: str | None = Field(default=None, description="数据源 key")

    # 时间周期
    period_role: PeriodRole = Field(description="该子查询的时间周期角色")
    time_period: str | None = Field(default=None, description="具体时间周期")

    # 过滤条件
    group_by: str | None = Field(default=None, description="该子查询的分组维度")
    filters: dict = Field(default_factory=dict, description="该子查询的额外过滤条件")

    # 关联信息（用于 JOIN）
    join_with: str | None = Field(default=None, description="关联的另一个 query_id（用于 JOIN）")
    join_type: str | None = Field(default=None, description="JOIN 类型：inner/left/right")


class ExecutionPhase(BaseModel):
    """执行阶段结构。

    同一执行阶段内的查询会在同一数据源上执行。
    execution_strategy 定义了具体的执行策略。
    """

    phase_id: str = Field(description="阶段唯一标识")
    data_source_key: str = Field(description="数据源 key")
    queries: list[str] = Field(description="子查询 ID 列表")
    strategy: ExecutionStrategy = Field(description="执行策略：single/parallel/join")
    join_sql: str | None = Field(default=None, description="JOIN SQL（当 strategy=join 时）")
    dependencies: list[str] = Field(default_factory=list, description="前置依赖阶段 ID")


class ExecutionPlan(BaseModel):
    """执行计划结构。

    定义了完整查询的执行策略：
    - 按数据源分组为多个阶段
    - 阶段内根据策略执行（SINGLE/PARALLEL/JOIN）
    - 不同数据源的阶段可以并行执行
    - 需要应用层合并时标记 need_merge
    """

    phases: list[ExecutionPhase] = Field(default_factory=list, description="执行阶段列表")
    need_merge: bool = Field(default=False, description="是否需要应用层合并结果")
    total_queries: int = Field(default=0, description="总查询数")

    @field_validator("total_queries", mode="before")
    @classmethod
    def calculate_total(cls, v: int | None, info) -> int:
        if v is not None:
            return v
        phases = info.data.get("phases", [])
        return sum(len(p.queries) for p in phases)


class IntentConfidence(BaseModel):
    """意图解析整体置信度结构。"""

    overall: float = Field(description="整体置信度，0-1", ge=0.0, le=1.0)
    semantic: float | None = Field(default=None, description="语义理解置信度", ge=0.0, le=1.0)
    metric: float | None = Field(default=None, description="指标选择置信度", ge=0.0, le=1.0)
    time_range: float | None = Field(default=None, description="时间范围解析置信度", ge=0.0, le=1.0)
    org_scope: float | None = Field(default=None, description="组织范围解析置信度", ge=0.0, le=1.0)
    execution: float | None = Field(default=None, description="执行可行性置信度", ge=0.0, le=1.0)


class ClarificationOption(BaseModel):
    """澄清选项结构。"""

    field: str = Field(description="需要澄清的字段")
    type: ClarificationType = Field(description="澄清类型")
    value: str = Field(description="选项值")
    label: str = Field(description="选项显示名称")
    description: str | None = Field(default=None, description="选项描述")


# =============================================================================
# 主结构定义
# =============================================================================


class AnalyticsIntent(BaseModel):
    """经营分析统一意图结构。

    这是 LLM 统一解析的结果，包含了经营分析查询的所有必要信息。

    核心字段：
    - semantic_confidence: 语义理解置信度（是否听懂用户）
    - metric: 指标意图（含候选，用于歧义检测）
    - metric_confidence: 口径置信度（是否选对指标）
    - required_queries: 子查询列表（需要哪些 SQL）
    - execution_plan: 执行计划（如何执行这些 SQL）

    执行流程：
    1. LLM 解析 → AnalyticsIntent
    2. 歧义检测 → 需要澄清？
    3. QueryPlanner → 生成 ExecutionPlan（决定 JOIN/PARALLEL/SINGLE）
    4. QueryExecutor → 执行 SQL
    5. 应用层合并 → 返回结果
    """

    # 任务类型
    task_type: Literal["analytics_query"] = Field(
        default="analytics_query",
        description="任务类型"
    )

    # 原始问句
    original_query: str = Field(description="用户原始问句")

    # 复杂度
    complexity: ComplexityType = Field(description="问题复杂度")

    # 规划模式
    planning_mode: PlanningMode = Field(description="执行模式")

    # 分析意图
    analysis_intent: AnalysisIntentType = Field(description="分析意图类型")

    # 语义理解置信度
    semantic_confidence: float = Field(
        description="LLM 对用户意图的理解置信度，0-1",
        ge=0.0, le=1.0
    )

    # 核心槽位
    metric: MetricIntent | None = Field(default=None, description="指标意图")
    time_range: TimeRangeIntent | None = Field(default=None, description="时间范围意图")
    org_scope: OrgScopeIntent | None = Field(default=None, description="组织范围意图")

    # 分组与对比
    group_by: str | None = Field(default=None, description="分组维度")
    compare_target: CompareTarget = Field(default=CompareTarget.NONE, description="对比目标")
    sort_by: str | None = Field(default=None, description="排序字段")
    sort_direction: Literal["asc", "desc"] | None = Field(default=None, description="排序方向")
    top_n: int | None = Field(default=None, description="返回数量限制", ge=1, le=100)

    # 子查询列表（complex 时由 LLM 生成）
    required_queries: list[RequiredQuery] = Field(
        default_factory=list,
        description="复杂查询需要的子查询列表"
    )

    # 执行计划（由 QueryPlanner 填充）
    execution_plan: ExecutionPlan | None = Field(
        default=None,
        description="执行计划（子查询规划后填充）"
    )

    # 置信度
    confidence: IntentConfidence = Field(description="意图解析置信度")

    # 澄清状态
    need_clarification: bool = Field(description="是否需要用户澄清")
    clarification_type: ClarificationType | None = Field(default=None, description="澄清类型")
    clarification_question: str | None = Field(default=None, description="澄清问题文本")
    clarification_options: list[ClarificationOption] = Field(
        default_factory=list,
        description="澄清选项列表"
    )

    # 缺失/歧义字段
    missing_fields: list[str] = Field(default_factory=list, description="缺失字段列表")
    ambiguous_fields: list[str] = Field(default_factory=list, description="歧义字段列表")

    @field_validator("group_by", "sort_by", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("top_n", mode="before")
    @classmethod
    def validate_top_n(cls, v: int | None) -> int | None:
        if v is not None:
            return max(1, min(100, v))
        return v

    def has_metric_ambiguity(self) -> bool:
        """判断是否存在指标歧义。"""
        if self.metric is None:
            return False
        return len(self.metric.candidates) >= 2

    def needs_execution_plan(self) -> bool:
        """判断是否需要生成执行计划。"""
        return self.complexity == ComplexityType.COMPLEX and len(self.required_queries) > 0


class ClarificationResponse(BaseModel):
    """澄清响应结构。

    当 need_clarification=true 时返回给用户的澄清信息。
    """

    need_clarification: bool = Field(description="是否需要澄清")
    clarification_type: ClarificationType | None = Field(default=None, description="澄清类型")
    question: str = Field(description="澄清问题")
    options: list[ClarificationOption] = Field(default_factory=list, description="澄清选项")
    context: dict = Field(default_factory=dict, description="上下文信息（用于后续恢复）")

    @classmethod
    def from_intent(cls, intent: AnalyticsIntent) -> ClarificationResponse:
        """从 AnalyticsIntent 创建澄清响应。"""
        return cls(
            need_clarification=intent.need_clarification,
            clarification_type=intent.clarification_type,
            question=intent.clarification_question or "请补充更多信息",
            options=intent.clarification_options,
            context={
                "original_query": intent.original_query,
                "partial_intent": intent.model_dump(exclude={"execution_plan"}),
            },
        )
