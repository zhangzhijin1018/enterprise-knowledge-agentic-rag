"""经营分析歧义检测与澄清管理器（ClarificationManager）。

核心职责：
1. 检测意图解析结果中的歧义
2. 检测缺失的关键字段
3. 生成澄清问题和选项
4. 处理用户澄清响应

设计原则：
- 歧义检测是纯本地逻辑，不调用 LLM
- 歧义类型：指标歧义、时间范围缺失、指标缺失
- 澄清响应包含完整上下文，便于后续恢复执行
"""

from __future__ import annotations

from dataclasses import dataclass

from core.analytics.intent.schema import (
    AnalyticsIntent,
    ClarificationOption,
    ClarificationResponse,
    ClarificationType,
    ComplexityType,
    MetricCandidate,
    MetricIntent,
    PlanningMode,
)
from core.analytics.metric_resolver import MetricMetadata, MetricResolver


@dataclass
class ClarificationContext:
    """澄清上下文。

    包含澄清所需的完整上下文信息，用于恢复执行。
    """

    # 原始意图信息
    original_query: str
    partial_intent: dict

    # 澄清历史（多轮澄清时使用）
    clarification_history: list[dict] = None

    # 用户已确认的选择
    confirmed_selections: dict[str, str] = None

    def __post_init__(self):
        if self.clarification_history is None:
            self.clarification_history = []
        if self.confirmed_selections is None:
            self.confirmed_selections = {}


class ClarificationManager:
    """歧义检测与澄清管理器。

    使用示例：

    1. 检测歧义：
        manager = ClarificationManager(metric_resolver)
        intent = parser.parse("分析新疆最近电量下降的原因")
        clarification = manager.detect_ambiguity(intent)

        if clarification.need_clarification:
            return clarification.question  # 返回给用户

    2. 处理澄清响应：
        user_choice = "generation"  # 用户选择了"发电量"
        updated_context = manager.apply_clarification(context, user_choice)

        # 使用确认的选择更新意图
        updated_intent = manager.apply_to_intent(intent, updated_context)
    """

    def __init__(self, metric_resolver: MetricResolver) -> None:
        self.metric_resolver = metric_resolver

        # 指标缺失时的默认选项
        self._common_metrics = [
            "generation",
            "revenue",
            "cost",
            "profit",
        ]

    def detect_ambiguity(self, intent: AnalyticsIntent) -> ClarificationResponse:
        """检测意图中的歧义。

        检测顺序：
        1. 指标歧义（candidates >= 2）
        2. 指标缺失
        3. 时间范围缺失
        4. 组织范围缺失

        Args:
            intent: LLM 解析后的意图

        Returns:
            ClarificationResponse: 包含是否需要澄清及具体问题
        """

        # 检测指标歧义
        if self._has_metric_ambiguity(intent):
            return self._create_metric_ambiguity_response(intent)

        # 检测指标缺失
        if self._has_metric_missing(intent):
            return self._create_metric_missing_response(intent)

        # 检测时间范围缺失
        if self._has_time_range_missing(intent):
            return self._create_time_range_missing_response(intent)

        # 检测组织范围缺失（可选，可能不需要澄清）
        # if self._has_org_scope_missing(intent):
        #     return self._create_org_scope_missing_response(intent)

        # 无需澄清
        return ClarificationResponse(
            need_clarification=False,
            question="",
            options=[],
            context={
                "original_query": intent.original_query,
                "partial_intent": intent.model_dump(exclude={"execution_plan"}),
            },
        )

    def _has_metric_ambiguity(self, intent: AnalyticsIntent) -> bool:
        """判断是否存在指标歧义。"""

        if intent.metric is None:
            return False

        # 有多个候选时存在歧义
        has_candidates = len(intent.metric.candidates) >= 2

        # 或者候选置信度接近（最大置信度 < 0.7）
        max_confidence = (
            max(c.confidence for c in intent.metric.candidates)
            if intent.metric.candidates else 0
        )
        low_confidence = max_confidence < 0.7 and len(intent.metric.candidates) >= 2

        return has_candidates or low_confidence

    def _has_metric_missing(self, intent: AnalyticsIntent) -> bool:
        """判断是否缺失指标。"""

        if intent.metric is None:
            return True

        if intent.metric.metric_code is None and len(intent.metric.candidates) == 0:
            return True

        return False

    def _has_time_range_missing(self, intent: AnalyticsIntent) -> bool:
        """判断是否缺失时间范围。"""

        # 简单查询必须有时间范围
        if intent.complexity == ComplexityType.SIMPLE:
            return intent.time_range is None

        # 复杂查询也需要时间范围（用于确定分析周期）
        return intent.time_range is None

    def _create_metric_ambiguity_response(
        self,
        intent: AnalyticsIntent,
    ) -> ClarificationResponse:
        """创建指标歧义澄清响应。"""

        candidates = intent.metric.candidates

        # 构建澄清选项
        options = []
        for i, candidate in enumerate(candidates, 1):
            # 获取指标的详细信息
            try:
                metadata = self.metric_resolver.resolve(candidate.metric_code)
                description = metadata.description
            except ValueError:
                description = ""

            options.append(
                ClarificationOption(
                    field="metric",
                    type=ClarificationType.METRIC_AMBIGUITY,
                    value=candidate.metric_code,
                    label=candidate.metric_name,
                    description=description,
                )
            )

        # 生成澄清问题
        if len(candidates) == 2:
            question = f"您说的「{intent.metric.raw_text}」是指：\n1. {candidates[0].metric_name}\n2. {candidates[1].metric_name}\n\n请回复选项编号或指标名称。"
        else:
            options_text = "\n".join(
                f"{i + 1}. {c.metric_name}" for i, c in enumerate(candidates)
            )
            question = f"您说的「{intent.metric.raw_text}」可能有以下几种含义：\n{options_text}\n\n请回复选项编号或指标名称。"

        # 更新意图的澄清状态
        intent.need_clarification = True
        intent.clarification_type = ClarificationType.METRIC_AMBIGUITY
        intent.clarification_question = question
        intent.clarification_options = options
        intent.planning_mode = PlanningMode.CLARIFICATION

        return ClarificationResponse(
            need_clarification=True,
            clarification_type=ClarificationType.METRIC_AMBIGUITY,
            question=question,
            options=options,
            context={
                "original_query": intent.original_query,
                "partial_intent": intent.model_dump(exclude={"execution_plan"}),
                "ambiguous_field": "metric",
                "candidates": [c.model_dump() for c in candidates],
            },
        )

    def _create_metric_missing_response(
        self,
        intent: AnalyticsIntent,
    ) -> ClarificationResponse:
        """创建指标缺失澄清响应。"""

        # 获取常用指标作为选项
        options = []
        for metric_code in self._common_metrics:
            try:
                metadata = self.metric_resolver.resolve(metric_code)
                options.append(
                    ClarificationOption(
                        field="metric",
                        type=ClarificationType.METRIC_MISSING,
                        value=metric_code,
                        label=metadata.metric_name,
                        description=metadata.description,
                    )
                )
            except ValueError:
                continue

        # 也添加意图中已有的候选（如果有）
        if intent.metric and intent.metric.candidates:
            for candidate in intent.metric.candidates:
                if candidate.metric_code not in [o.value for o in options]:
                    options.append(
                        ClarificationOption(
                            field="metric",
                            type=ClarificationType.METRIC_MISSING,
                            value=candidate.metric_code,
                            label=candidate.metric_name,
                            description="",
                        )
                    )

        question = "请问您想查看哪个经营指标？"
        if intent.metric and intent.metric.raw_text:
            question = f"关于「{intent.metric.raw_text}」，请问您想查看哪个指标？"

        # 更新意图的澄清状态
        intent.need_clarification = True
        intent.clarification_type = ClarificationType.METRIC_MISSING
        intent.clarification_question = question
        intent.clarification_options = options
        intent.planning_mode = PlanningMode.CLARIFICATION

        return ClarificationResponse(
            need_clarification=True,
            clarification_type=ClarificationType.METRIC_MISSING,
            question=question,
            options=options,
            context={
                "original_query": intent.original_query,
                "partial_intent": intent.model_dump(exclude={"execution_plan"}),
                "missing_field": "metric",
            },
        )

    def _create_time_range_missing_response(
        self,
        intent: AnalyticsIntent,
    ) -> ClarificationResponse:
        """创建时间范围缺失澄清响应。"""

        options = [
            ClarificationOption(
                field="time_range",
                type=ClarificationType.TIME_RANGE_MISSING,
                value="本月",
                label="本月",
                description="当前月份",
            ),
            ClarificationOption(
                field="time_range",
                type=ClarificationType.TIME_RANGE_MISSING,
                value="上月",
                label="上月",
                description="上一个完整月份",
            ),
            ClarificationOption(
                field="time_range",
                type=ClarificationType.TIME_RANGE_MISSING,
                value="近3个月",
                label="近3个月",
                description="最近3个月",
            ),
            ClarificationOption(
                field="time_range",
                type=ClarificationType.TIME_RANGE_MISSING,
                value="今年",
                label="今年",
                description="本年度1月至今",
            ),
            ClarificationOption(
                field="time_range",
                type=ClarificationType.TIME_RANGE_MISSING,
                value="去年",
                label="去年",
                description="上一完整年度",
            ),
        ]

        question = "请问您想查看哪个时间范围的指标？"

        # 更新意图的澄清状态
        intent.need_clarification = True
        intent.clarification_type = ClarificationType.TIME_RANGE_MISSING
        intent.clarification_question = question
        intent.clarification_options = options
        intent.planning_mode = PlanningMode.CLARIFICATION

        return ClarificationResponse(
            need_clarification=True,
            clarification_type=ClarificationType.TIME_RANGE_MISSING,
            question=question,
            options=options,
            context={
                "original_query": intent.original_query,
                "partial_intent": intent.model_dump(exclude={"execution_plan"}),
                "missing_field": "time_range",
            },
        )

    def apply_clarification(
        self,
        context: ClarificationContext,
        user_response: str,
    ) -> ClarificationContext:
        """应用用户澄清响应。

        Args:
            context: 澄清上下文
            user_response: 用户的响应（可以是选项编号或直接输入）

        Returns:
            更新后的上下文
        """

        # 记录历史
        context.clarification_history.append({
            "response": user_response,
        })

        # 尝试解析用户响应
        # 1. 如果是数字，尝试作为选项编号
        # 2. 如果是文本，尝试作为指标代码或名称

        resolved_value = self._resolve_user_response(user_response, context)

        # 记录已确认的选择
        if resolved_value:
            # 从最后一个选项获取字段名
            if context.partial_intent.get("clarification_options"):
                last_options = context.partial_intent["clarification_options"]
                if last_options:
                    field = last_options[-1].get("field", "metric")
                    context.confirmed_selections[field] = resolved_value

        return context

    def _resolve_user_response(
        self,
        user_response: str,
        context: ClarificationContext,
    ) -> str | None:
        """解析用户响应。"""

        user_response = user_response.strip()

        # 获取澄清选项
        options = context.partial_intent.get("clarification_options", [])
        if not options:
            return user_response  # 无法解析，直接返回

        # 尝试作为编号解析
        try:
            idx = int(user_response) - 1
            if 0 <= idx < len(options):
                return options[idx].get("value")
        except ValueError:
            pass

        # 尝试作为值直接匹配
        for option in options:
            if option.get("value") == user_response:
                return user_response
            if option.get("label") == user_response:
                return option.get("value")

        # 尝试作为指标名称匹配
        for option in options:
            if option.get("label") and option.get("label") in user_response:
                return option.get("value")

        return user_response  # 无法匹配，返回原始响应

    def apply_to_intent(
        self,
        intent: AnalyticsIntent,
        context: ClarificationContext,
    ) -> AnalyticsIntent:
        """将澄清结果应用到意图。

        Args:
            intent: 原始意图
            context: 澄清上下文

        Returns:
            更新后的意图
        """

        confirmed = context.confirmed_selections

        # 应用指标选择
        if "metric" in confirmed:
            metric_code = confirmed["metric"]
            try:
                metadata = self.metric_resolver.resolve(metric_code)
                intent.metric = MetricIntent(
                    raw_text=metadata.metric_name,
                    metric_code=metric_code,
                    metric_name=metadata.metric_name,
                    confidence=1.0,
                    candidates=[],
                )
                intent.need_clarification = False
                intent.clarification_type = None
                intent.clarification_question = None
                intent.clarification_options = []
            except ValueError:
                pass

        # 应用时间范围选择
        if "time_range" in confirmed:
            time_value = confirmed["time_range"]
            intent.time_range = self._parse_time_range(time_value)
            intent.need_clarification = False

        return intent

    def _parse_time_range(self, value: str) -> dict | None:
        """解析时间范围值。"""

        import re
        from core.analytics.intent.schema import TimeRangeIntent, TimeRangeType

        if value == "本月":
            return TimeRangeIntent(
                raw_text="本月",
                type=TimeRangeType.RELATIVE,
                value="本月",
                confidence=1.0,
            )
        elif value == "上月":
            return TimeRangeIntent(
                raw_text="上月",
                type=TimeRangeType.RELATIVE,
                value="上月",
                confidence=1.0,
            )
        elif value == "今年":
            return TimeRangeIntent(
                raw_text="今年",
                type=TimeRangeType.RELATIVE,
                value="今年",
                confidence=1.0,
            )
        elif value == "去年":
            return TimeRangeIntent(
                raw_text="去年",
                type=TimeRangeType.RELATIVE,
                value="去年",
                confidence=1.0,
            )
        elif "近" in value and "个月" in value:
            match = re.search(r"(\d+)个月", value)
            if match:
                return TimeRangeIntent(
                    raw_text=value,
                    type=TimeRangeType.RELATIVE,
                    value=f"近{match.group(1)}个月",
                    confidence=1.0,
                )

        return None


# =============================================================================
# 便捷函数
# =============================================================================


def detect_and_clarify(
    intent: AnalyticsIntent,
    metric_resolver: MetricResolver,
) -> ClarificationResponse:
    """便捷函数：检测歧义并返回澄清响应。"""

    manager = ClarificationManager(metric_resolver)
    return manager.detect_ambiguity(intent)
