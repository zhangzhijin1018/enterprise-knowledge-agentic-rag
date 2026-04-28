"""经营分析 Planner 的 LLM fallback 适配层。

设计目标：
1. 不让 `analytics_planner.py` 直接耦合任何具体 LLM SDK；
2. 把“规则不足时，如何让 LLM 做结构化补强”收口到独立模块；
3. 即使当前没有真实 LLM 配置，也能返回清晰、可测试、可扩展的占位结构；
4. 明确限制：LLM 只能补强槽位，不允许直接从自然语言生成 SQL。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.config.settings import Settings


@dataclass(slots=True)
class LLMAnalyticsPlannerResult:
    """LLM fallback 结构化输出。"""

    slots: dict = field(default_factory=dict)
    clarification_question: str | None = None
    clarification_target_slots: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "disabled"
    should_use: bool = False


class LLMAnalyticsPlannerGateway:
    """经营分析 Planner 的 LLM fallback 网关。

    当前阶段的设计约束：
    - 有真实 LLM 配置时，可以通过注入 adapter / callable 走真实调用；
    - 无真实 LLM 配置时，返回清晰占位结构；
    - 返回结果必须仍然是结构化槽位，而不是自然语言长文本。
    """

    def __init__(
        self,
        *,
        settings: Settings,
        planner_callable=None,
    ) -> None:
        self.settings = settings
        self.planner_callable = planner_callable

    def enhance_slots(
        self,
        *,
        query: str,
        current_slots: dict,
        conversation_memory: dict | None,
    ) -> LLMAnalyticsPlannerResult:
        """尝试用 LLM 对规则结果做补强。"""

        if not self.settings.analytics_planner_enable_llm_fallback:
            return LLMAnalyticsPlannerResult(
                source="disabled",
                should_use=False,
                confidence=0.0,
            )

        if self.planner_callable is None:
            # 当前阶段没有真实模型接入时，明确返回“已启用 fallback 开关，
            # 但暂无实际 provider”，方便后续排查，而不是静默吞掉。
            return LLMAnalyticsPlannerResult(
                source="placeholder",
                should_use=False,
                confidence=0.2,
            )

        raw_result = self.planner_callable(
            query=query,
            current_slots=current_slots,
            conversation_memory=conversation_memory or {},
        )
        if isinstance(raw_result, LLMAnalyticsPlannerResult):
            return raw_result

        # 允许注入简单 dict，便于测试时 mock。
        return LLMAnalyticsPlannerResult(
            slots=raw_result.get("slots", {}),
            clarification_question=raw_result.get("clarification_question"),
            clarification_target_slots=raw_result.get("clarification_target_slots", []),
            confidence=float(raw_result.get("confidence", 0.0)),
            source=raw_result.get("source", "adapter"),
            should_use=bool(raw_result.get("should_use", False)),
        )
