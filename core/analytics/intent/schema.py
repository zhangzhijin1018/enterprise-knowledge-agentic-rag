# Analytics Intent Schema - 经营分析意图识别 Pydantic 模型
"""
经营分析 Agent 意图识别模块的 Schema 定义。

本模块定义了用于结构化表示用户查询意图的 Pydantic 模型，包括：
- 分析意图类型（AnalysisIntentType）
- 时间范围意图（TimeRangeIntent）
- 组织范围意图（OrgScopeIntent）
- 指标意图（MetricIntent）
- 统一分析意图（AnalyticsIntent）
- 置信度级别（IntentConfidence）
- 意图验证结果（IntentValidationResult）

设计原则：
1. 所有字段必须有中文注释
2. 使用枚举约束可选值
3. 支持 optional 字段的默认值处理
4. 与 AnalyticsPlanner 的槽位模型保持一致
"""

from datetime import date
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================================
# 枚举定义
# ============================================================================


class AnalysisIntentType(str, Enum):
    """分析意图类型枚举。

    用于标识用户查询的主要分析目的。

    - single_metric: 单指标查询，如"查询发电量"
    - comparison: 对比分析，如"与去年对比"
    - trend: 趋势分析，如"近三个月变化"
    - ranking: 排名分析，如"哪些电站最高"
    - breakdown: 维度拆解，如"按电站分组"
    - root_cause: 根因分析，如"下降原因"
    - complex: 复杂组合，如多意图组合
    """

    SINGLE_METRIC = "single_metric"
    COMPARISON = "comparison"
    TREND = "trend"
    RANKING = "ranking"
    BREAKDOWN = "breakdown"
    ROOT_CAUSE = "root_cause"
    COMPLEX = "complex"


class TimeRangeType(str, Enum):
    """时间范围类型枚举。

    用于标识时间范围的识别方式。

    - absolute_date: 绝对日期，如"2024-03-01"
    - absolute_month: 绝对月份，如"2024年3月"
    - relative_days: 相对天数，如"近30天"
    - relative_week: 相对周，如"本周"
    - relative_month: 相对月，如"上个月"
    - quarter: 季度，如"2024年Q1"
    - year: 年份，如"2024年"
    """

    ABSOLUTE_DATE = "absolute_date"
    ABSOLUTE_MONTH = "absolute_month"
    RELATIVE_DAYS = "relative_days"
    RELATIVE_WEEK = "relative_week"
    RELATIVE_MONTH = "relative_month"
    QUARTER = "quarter"
    YEAR = "year"


class OrgScopeType(str, Enum):
    """组织范围类型枚举。

    用于标识组织范围的识别方式。

    - group: 集团级别
    - region: 区域级别，如"新疆区域"
    - department: 部门级别
    - station: 电站级别，如"哈密电站"
    """

    GROUP = "group"
    REGION = "region"
    DEPARTMENT = "department"
    STATION = "station"


class PeriodRole(str, Enum):
    """时间段角色枚举。

    用于标识时间段在对比分析中的角色。

    - current: 当前时间段
    - compare: 对比时间段
    """

    CURRENT = "current"
    COMPARE = "compare"


class CompareTarget(str, Enum):
    """对比目标类型枚举。

    用于标识对比分析的目标类型。

    - yoy: 同比（Year over Year）
    - mom: 环比（Month over Month）
    - qoq: 季度环比
    - custom: 自定义对比
    """

    YOY = "yoy"
    MOM = "mom"
    QOQ = "qoq"
    CUSTOM = "custom"


class SortDirection(str, Enum):
    """排序方向枚举。

    用于标识排名分析的排序方向。

    - asc: 升序（从小到大）
    - desc: 降序（从大到小）
    """

    ASC = "asc"
    DESC = "desc"


class IntentConfidence(str, Enum):
    """意图置信度级别枚举。

    用于标识意图识别的置信度级别。

    - high: 高置信度，规则明确匹配
    - medium: 中置信度，规则部分匹配
    - low: 低置信度，需要 LLM 辅助
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AnalyticsIntentComplexity(str, Enum):
    """分析意图复杂度枚举。

    用于标识分析意图的复杂度级别。

    - simple: 简单查询，单指标+单时间+单组织
    - moderate: 中等复杂度，包含分组或对比
    - complex: 复杂查询，多意图组合或多步推理
    """

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class AnalyticsIntentPlanningMode(str, Enum):
    """分析意图规划模式枚举。

    用于标识规划阶段使用的模式。

    - rule: 规则模式，基于正则和关键词匹配
    - llm_slot_fallback: LLM 槽位补强模式
    - react: ReAct 规划模式，多步推理
    """

    RULE = "rule"
    LLM_SLOT_FALLBACK = "llm_slot_fallback"
    REACT = "react"


# ============================================================================
# 时间范围意图模型
# ============================================================================


class TimeRangeIntent(BaseModel):
    """时间范围意图模型。

    用于结构化表示用户查询中的时间范围信息。

    Attributes:
        type: 时间范围类型，标识是绝对日期还是相对时间
        label: 时间范围的可读标签，用于前端展示
        start_date: 查询开始日期
        end_date: 查询结束日期
        period_role: 时间段在对比分析中的角色
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "description": "时间范围意图模型",
            "example": {
                "type": "absolute_month",
                "label": "2024年3月",
                "start_date": "2024-03-01",
                "end_date": "2024-03-31",
                "period_role": "current",
            },
        },
    )

    type: TimeRangeType = Field(
        description="时间范围类型，标识是绝对日期还是相对时间",
    )

    label: str = Field(
        description="时间范围的可读标签，用于前端展示和日志记录",
        examples=["2024年3月", "近30天", "上个月"],
    )

    start_date: Optional[date] = Field(
        default=None,
        description="查询开始日期，当 type 为 absolute_date 或 absolute_month 时必填",
    )

    end_date: Optional[date] = Field(
        default=None,
        description="查询结束日期，当 type 为 absolute_date 或 absolute_month 时必填",
    )

    period_role: PeriodRole = Field(
        default=PeriodRole.CURRENT,
        description="时间段在对比分析中的角色，用于区分当前期和对比期",
    )

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def parse_date(cls, v: Optional[str | date]) -> Optional[date]:
        """解析日期字符串或返回 date 对象。"""
        if v is None:
            return None
        if isinstance(v, date):
            return v
        if isinstance(v, str):
            return date.fromisoformat(v)
        return v


# ============================================================================
# 组织范围意图模型
# ============================================================================


class OrgCandidate(BaseModel):
    """组织候选模型。

    表示一个可能的组织实体，用于模糊匹配或候选展示。

    Attributes:
        value: 组织值，如"新疆区域"、"哈密电站"
        type: 组织类型，如 region、station
        display_name: 显示名称
        matched: 是否直接匹配
        confidence: 匹配置信度
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "description": "组织候选模型",
            "example": {
                "value": "新疆区域",
                "type": "region",
                "display_name": "新疆区域",
                "matched": True,
                "confidence": 0.95,
            },
        },
    )

    value: str = Field(
        description="组织值，如区域名、电站名、部门名",
        examples=["新疆区域", "哈密电站", "经营管理部"],
    )

    type: OrgScopeType = Field(
        description="组织类型，标识组织层级",
    )

    display_name: str = Field(
        description="显示名称，用于前端展示",
    )

    matched: bool = Field(
        default=True,
        description="是否直接匹配，false 表示需要用户确认",
    )

    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="匹配置信度，0-1 之间",
    )


class OrgScopeIntent(BaseModel):
    """组织范围意图模型。

    用于结构化表示用户查询中的组织范围信息。

    Attributes:
        type: 组织范围类型
        value: 组织范围的具体值
        candidates: 候选组织列表，用于模糊匹配时的选项
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "description": "组织范围意图模型",
            "example": {
                "type": "region",
                "value": "新疆区域",
                "candidates": [
                    {
                        "value": "新疆区域",
                        "type": "region",
                        "display_name": "新疆区域",
                        "matched": True,
                        "confidence": 0.95,
                    }
                ],
            },
        },
    )

    type: OrgScopeType = Field(
        description="组织范围类型，标识组织层级",
    )

    value: str = Field(
        description="组织范围的具体值，如区域名、电站名",
        examples=["新疆区域", "哈密电站"],
    )

    candidates: list[OrgCandidate] = Field(
        default_factory=list,
        description="候选组织列表，用于模糊匹配时提供选项",
    )


# ============================================================================
# 指标意图模型
# ============================================================================


class MetricCandidate(BaseModel):
    """指标候选模型。

    表示一个可能的指标实体，用于模糊匹配或候选展示。

    Attributes:
        name: 指标名称，如"发电量"、"收入"
        code: 指标编码，如"power_generation"、"revenue"
        display_name: 显示名称
        unit: 单位，如"MWh"、"万元"
        matched: 是否直接匹配
        confidence: 匹配置信度
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "description": "指标候选模型",
            "example": {
                "name": "发电量",
                "code": "power_generation",
                "display_name": "发电量",
                "unit": "MWh",
                "matched": True,
                "confidence": 0.92,
            },
        },
    )

    name: str = Field(
        description="指标名称，如发电量、收入",
        examples=["发电量", "收入", "成本"],
    )

    code: str = Field(
        description="指标编码，用于系统内部处理",
        examples=["power_generation", "revenue", "cost"],
    )

    display_name: str = Field(
        description="显示名称，用于前端展示",
    )

    unit: Optional[str] = Field(
        default=None,
        description="单位，如 MWh、万元",
        examples=["MWh", "万元"],
    )

    matched: bool = Field(
        default=True,
        description="是否直接匹配，false 表示需要用户确认",
    )

    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="匹配置信度，0-1 之间",
    )


class MetricIntent(BaseModel):
    """指标意图模型。

    用于结构化表示用户查询中的指标信息。

    Attributes:
        name: 指标名称
        code: 指标编码
        candidates: 候选指标列表，用于模糊匹配时的选项
        fallback_used: 是否使用了 LLM fallback
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "description": "指标意图模型",
            "example": {
                "name": "发电量",
                "code": "power_generation",
                "candidates": [
                    {
                        "name": "发电量",
                        "code": "power_generation",
                        "display_name": "发电量",
                        "unit": "MWh",
                        "matched": True,
                        "confidence": 0.92,
                    }
                ],
                "fallback_used": False,
            },
        },
    )

    name: str = Field(
        description="指标名称，如发电量、收入",
        examples=["发电量", "收入"],
    )

    code: str = Field(
        description="指标编码，用于系统内部处理",
        examples=["power_generation", "revenue"],
    )

    candidates: list[MetricCandidate] = Field(
        default_factory=list,
        description="候选指标列表，用于模糊匹配时提供选项",
    )

    fallback_used: bool = Field(
        default=False,
        description="是否使用了 LLM fallback，当规则置信度低时由 LLM 补强",
    )


# ============================================================================
# 统一分析意图模型
# ============================================================================


class AnalyticsIntent(BaseModel):
    """统一分析意图模型。

    用于结构化表示用户经营分析查询的完整意图。

    这是意图识别的最终输出，包含了执行分析所需的所有槽位信息。

    Attributes:
        intent_type: 分析意图类型，如 single_metric、comparison、trend
        metric: 指标意图
        time_range: 时间范围意图
        org_scope: 组织范围意图
        compare_target: 对比目标类型
        group_by: 分组维度
        sort_direction: 排序方向
        top_n: 返回前 N 条
        confidence: 置信度级别
        complexity: 复杂度级别
        planning_mode: 规划模式
        is_executable: 是否满足最小可执行条件
        missing_slots: 缺失的槽位列表
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "description": "统一分析意图模型",
            "example": {
                "intent_type": "single_metric",
                "metric": {
                    "name": "发电量",
                    "code": "power_generation",
                    "candidates": [],
                    "fallback_used": False,
                },
                "time_range": {
                    "type": "absolute_month",
                    "label": "2024年3月",
                    "start_date": "2024-03-01",
                    "end_date": "2024-03-31",
                    "period_role": "current",
                },
                "org_scope": {
                    "type": "region",
                    "value": "新疆区域",
                    "candidates": [],
                },
                "compare_target": None,
                "group_by": None,
                "sort_direction": None,
                "top_n": None,
                "confidence": "high",
                "complexity": "simple",
                "planning_mode": "rule",
                "is_executable": True,
                "missing_slots": [],
            },
        },
    )

    intent_type: AnalysisIntentType = Field(
        description="分析意图类型，标识用户的主要分析目的",
    )

    metric: Optional[MetricIntent] = Field(
        default=None,
        description="指标意图，标识用户要查询的经营指标",
    )

    time_range: Optional[TimeRangeIntent] = Field(
        default=None,
        description="时间范围意图，标识用户要查询的时间范围",
    )

    org_scope: Optional[OrgScopeIntent] = Field(
        default=None,
        description="组织范围意图，标识用户要查询的组织范围",
    )

    compare_target: Optional[CompareTarget] = Field(
        default=None,
        description="对比目标类型，如同比(yoy)、环比(mom)",
    )

    group_by: Optional[str] = Field(
        default=None,
        description="分组维度，如 station、region、month",
        examples=["station", "region", "month"],
    )

    sort_direction: Optional[SortDirection] = Field(
        default=None,
        description="排序方向，用于排名分析",
    )

    top_n: Optional[int] = Field(
        default=None,
        ge=1,
        le=100,
        description="返回前 N 条，用于排名分析",
    )

    confidence: IntentConfidence = Field(
        default=IntentConfidence.HIGH,
        description="置信度级别，标识意图识别的整体置信度",
    )

    complexity: AnalyticsIntentComplexity = Field(
        default=AnalyticsIntentComplexity.SIMPLE,
        description="复杂度级别，标识分析意图的复杂程度",
    )

    planning_mode: AnalyticsIntentPlanningMode = Field(
        default=AnalyticsIntentPlanningMode.RULE,
        description="规划模式，标识规划阶段使用的模式",
    )

    is_executable: bool = Field(
        default=False,
        description="是否满足最小可执行条件，当所有必填槽位齐全时为 True",
    )

    missing_slots: list[str] = Field(
        default_factory=list,
        description="缺失的槽位列表，当 is_executable 为 False 时填充",
        examples=[["metric"], ["time_range"], ["metric", "time_range"]],
    )

    def get_required_slots(self) -> list[str]:
        """获取必填槽位列表。

        Returns:
            必填槽位名称列表，包括 metric 和 time_range
        """
        return ["metric", "time_range"]

    def get_collected_slots(self) -> dict[str, str]:
        """获取已收集的槽位字典。

        Returns:
            已收集槽位名称到值的字典
        """
        collected = {}
        if self.metric:
            collected["metric"] = self.metric.name
        if self.time_range:
            collected["time_range"] = self.time_range.label
        if self.org_scope:
            collected["org_scope"] = self.org_scope.value
        return collected


# ============================================================================
# 意图验证结果模型
# ============================================================================


class IntentValidationResult(BaseModel):
    """意图验证结果模型。

    用于表示意图验证的结果，包括是否可执行以及原因。

    Attributes:
        is_valid: 是否有效
        is_executable: 是否满足最小可执行条件
        missing_slots: 缺失的槽位列表
        slot_conflicts: 槽位冲突列表
        validation_errors: 验证错误列表
    """

    model_config = ConfigDict(
        json_schema_extra={
            "description": "意图验证结果模型",
            "example": {
                "is_valid": True,
                "is_executable": True,
                "missing_slots": [],
                "slot_conflicts": [],
                "validation_errors": [],
            },
        },
    )

    is_valid: bool = Field(
        description="是否有效，标识验证是否通过",
    )

    is_executable: bool = Field(
        default=False,
        description="是否满足最小可执行条件，当所有必填槽位齐全时为 True",
    )

    missing_slots: list[str] = Field(
        default_factory=list,
        description="缺失的槽位列表",
    )

    slot_conflicts: list[str] = Field(
        default_factory=list,
        description="槽位冲突列表，如同时指定了矛盾的维度",
    )

    validation_errors: list[str] = Field(
        default_factory=list,
        description="验证错误列表，包含具体的验证失败原因",
    )
