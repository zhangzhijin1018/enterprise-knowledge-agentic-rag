"""经营分析槽位校验器。

设计目标：
1. 把“缺不缺槽位、槽位是否冲突、是否满足最小可执行条件”从 Planner 中拆出来；
2. 让规则层显式掌控执行边界，而不是把这些决定交给 LLM；
3. 为后续更多业务场景复用“结构化校验 -> 澄清 -> 恢复执行”模式打底。

关键原则：
- 必填槽位判断必须是本地确定性规则；
- 冲突槽位判断必须是本地确定性规则；
- 是否允许执行 SQL 必须由这里明确给出，不允许 LLM 越权决定。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SlotValidationResult:
    """槽位校验结果。"""

    missing_slots: list[str] = field(default_factory=list)
    conflict_slots: list[str] = field(default_factory=list)
    is_executable: bool = False
    validation_reason: str = ""


class SlotValidator:
    """经营分析最小槽位校验器。"""

    def __init__(self, required_slots: list[str] | None = None) -> None:
        self.required_slots = required_slots or ["metric", "time_range"]

    def validate(self, slots: dict) -> SlotValidationResult:
        """校验当前槽位是否满足最小执行条件。"""

        missing_slots = [
            slot_name
            for slot_name in self.required_slots
            if slots.get(slot_name) in (None, "", {}, [])
        ]
        conflict_slots = self._detect_conflicts(slots)
        is_executable = not missing_slots and not conflict_slots

        if conflict_slots:
            validation_reason = f"存在冲突槽位：{', '.join(conflict_slots)}"
        elif missing_slots:
            validation_reason = f"缺少关键槽位：{', '.join(missing_slots)}"
        else:
            validation_reason = "已满足最小可执行条件"

        return SlotValidationResult(
            missing_slots=missing_slots,
            conflict_slots=conflict_slots,
            is_executable=is_executable,
            validation_reason=validation_reason,
        )

    def _detect_conflicts(self, slots: dict) -> list[str]:
        """检测冲突槽位。

        当前阶段最核心的冲突是“多主指标表达”：
        - 经营分析 V6 仍然坚持单主指标执行；
        - 如果用户一次提出多个指标，必须澄清，不允许系统擅自挑一个执行。
        """

        conflict_slots: list[str] = []
        metric_candidates = slots.get("metric_candidates") or []
        if len(metric_candidates) >= 2:
            conflict_slots.append("metric")
        return conflict_slots
