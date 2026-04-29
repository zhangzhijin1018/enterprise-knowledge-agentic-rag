"""经营分析 Human Review 策略。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AnalyticsReviewDecision:
    """经营分析审核策略决策结果。"""

    review_required: bool
    review_level: str
    review_reason: str | None
    reason_details: list[str] = field(default_factory=list)


class AnalyticsReviewPolicy:
    """经营分析审核策略层。

    设计原则：
    - Review 是否触发必须由确定性本地规则决定；
    - LLM 不参与“要不要审”的最终判断；
    - 当前阶段优先覆盖“导出前审核”，而不是把所有查询默认拉进审批。
    """

    FORMAL_EXPORT_TYPES = {"docx", "pdf"}

    def __init__(
        self,
        *,
        high_row_count_threshold: int = 100,
        high_sensitivity_levels: set[str] | None = None,
    ) -> None:
        self.high_row_count_threshold = high_row_count_threshold
        self.high_sensitivity_levels = high_sensitivity_levels or {"restricted", "high", "sensitive"}

    def evaluate_export(
        self,
        *,
        export_type: str,
        output_snapshot: dict,
        metric_definition,
        data_source_definition,
    ) -> AnalyticsReviewDecision:
        """评估一次经营分析导出是否需要进入 Human Review。"""

        reasons: list[str] = []
        review_level = "low"

        if export_type in self.FORMAL_EXPORT_TYPES:
            reasons.append("正式导出类型需要人工复核")
            review_level = self._raise_review_level(review_level, "high")

        if getattr(metric_definition, "sensitivity_level", "normal") in self.high_sensitivity_levels:
            reasons.append(f"指标敏感等级较高：{metric_definition.sensitivity_level}")
            review_level = self._raise_review_level(review_level, "high")

        if output_snapshot.get("masked_fields"):
            reasons.append("结果包含敏感字段治理或脱敏处理")
            review_level = self._raise_review_level(review_level, "high")

        row_count = output_snapshot.get("row_count") or 0
        if row_count >= self.high_row_count_threshold:
            reasons.append(f"结果返回行数较大：{row_count}")
            review_level = self._raise_review_level(review_level, "medium")

        if getattr(data_source_definition, "key", "") != "local_analytics":
            reasons.append(f"使用高敏或真实企业数据源：{data_source_definition.key}")
            review_level = self._raise_review_level(review_level, "high")

        governance_decision = output_snapshot.get("governance_decision") or {}
        if governance_decision.get("sensitive_fields"):
            reasons.append("治理决策识别到敏感字段参与分析")
            review_level = self._raise_review_level(review_level, "high")

        return AnalyticsReviewDecision(
            review_required=bool(reasons),
            review_level=review_level if reasons else "not_required",
            review_reason="；".join(reasons) if reasons else None,
            reason_details=reasons,
        )

    def _raise_review_level(self, current: str, target: str) -> str:
        """提升审核级别。"""

        order = {"low": 1, "medium": 2, "high": 3}
        return target if order.get(target, 0) > order.get(current, 0) else current
