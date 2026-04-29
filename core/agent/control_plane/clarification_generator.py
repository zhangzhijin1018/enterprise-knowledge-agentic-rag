"""经营分析澄清生成器。

职责：
1. 根据缺失槽位、冲突槽位和歧义场景生成结构化 clarification；
2. 先由规则模板确定澄清类型、目标槽位和 suggested options；
3. 如有 LLM fallback 提供更自然问法，可在不改变规则结论的前提下用于问句润色。

关键边界：
- 规则决定是否要澄清；
- 规则决定澄清的是哪个槽位；
- LLM 只能润色问法，不能改变“是否可执行”的结论。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ClarificationPayload:
    """结构化澄清结果。"""

    clarification_type: str
    question: str
    target_slots: list[str] = field(default_factory=list)
    reason: str = ""
    suggested_options: list[str] = field(default_factory=list)


class ClarificationGenerator:
    """经营分析澄清生成器。"""

    def generate(
        self,
        *,
        missing_slots: list[str],
        conflict_slots: list[str],
        current_slots: dict,
        validation_reason: str,
        llm_question: str | None = None,
    ) -> ClarificationPayload:
        """构造结构化 clarification。"""

        if "metric" in conflict_slots:
            candidates = current_slots.get("metric_candidates") or []
            question = llm_question or (
                f"你这次同时提到了多个指标：{'、'.join(candidates)}。当前最小版本建议先确定一个主指标，你想先看哪一个？"
            )
            return ClarificationPayload(
                clarification_type="slot_conflict",
                question=question,
                target_slots=["metric"],
                reason=validation_reason or "当前一次只支持一个主指标执行",
                suggested_options=candidates,
            )

        if "metric" in missing_slots:
            question = llm_question or (
                "当前分析范围已经基本确定，但还缺少主指标。你想看发电量、收入、成本、利润还是产量？"
                if current_slots.get("org_scope") or current_slots.get("time_range")
                else "你想看哪个指标？发电量、收入、成本、利润还是产量？"
            )
            return ClarificationPayload(
                clarification_type="missing_required_slot",
                question=question,
                target_slots=["metric"],
                reason=validation_reason or "缺少主指标，无法安全构造 SQL",
                suggested_options=["发电量", "收入", "成本", "利润", "产量"],
            )

        if "time_range" in missing_slots:
            return ClarificationPayload(
                clarification_type="missing_required_slot",
                question=llm_question or "你想看哪个时间范围？例如上个月、本月、2024年3月。",
                target_slots=["time_range"],
                reason=validation_reason or "缺少时间范围，无法安全构造 SQL",
                suggested_options=["上个月", "本月", "近一个月", "2024年3月"],
            )

        return ClarificationPayload(
            clarification_type="ambiguity",
            question=llm_question or "当前分析条件还不完整，请补充关键分析条件。",
            target_slots=(conflict_slots or missing_slots)[:2],
            reason=validation_reason or "当前表达仍存在歧义",
            suggested_options=[],
        )
