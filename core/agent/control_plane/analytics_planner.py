"""经营分析规划器。

当前阶段这里不是最终版 NL2SQL Planner，
而是一个“规则优先、槽位优先、安全优先”的控制面协调器。

本轮开始，它不再把所有逻辑都塞在一个文件里，而是逐步收口为：
- `SemanticResolver`：负责口语化语义补强、多轮上下文承接、LLM fallback 补槽位；
- `SlotValidator`：负责必填槽位、冲突槽位、最小可执行条件的本地确定性判断；
- `ClarificationGenerator`：负责把 missing/conflict/ambiguity 转成结构化澄清响应。

这样做的原因：
1. 澄清逻辑已经从“简单缺字段提示”升级成“经营分析助手的控制面能力”；
2. 必须明确哪些决策属于规则，哪些能力属于 LLM 补强；
3. 后续继续增强多轮承接、恢复执行和分析助手体验时，这个分层更稳。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.analytics.metric_catalog import MetricCatalog
from core.agent.control_plane.clarification_generator import (
    ClarificationGenerator,
    ClarificationPayload,
)
from core.agent.control_plane.llm_analytics_planner import LLMAnalyticsPlannerGateway
from core.agent.control_plane.semantic_resolver import SemanticResolver
from core.agent.control_plane.slot_validator import SlotValidationResult, SlotValidator


@dataclass(slots=True)
class AnalyticsPlan:
    """经营分析规划结果。"""

    intent: str
    slots: dict
    required_slots: list[str]
    missing_slots: list[str]
    conflict_slots: list[str]
    is_executable: bool
    clarification_question: str | None
    clarification_target_slots: list[str]
    clarification_type: str | None
    clarification_reason: str | None
    clarification_suggested_options: list[str]
    data_source: str | None
    planning_source: str
    confidence: float
    validation_reason: str


class AnalyticsPlanner:
    """经营分析最小规划器。"""

    REQUIRED_SLOTS = ["metric", "time_range"]

    def __init__(
        self,
        metric_catalog: MetricCatalog | None = None,
        llm_planner_gateway: LLMAnalyticsPlannerGateway | None = None,
        semantic_resolver: SemanticResolver | None = None,
        slot_validator: SlotValidator | None = None,
        clarification_generator: ClarificationGenerator | None = None,
    ) -> None:
        self.metric_catalog = metric_catalog or MetricCatalog()
        self.llm_planner_gateway = llm_planner_gateway
        self.semantic_resolver = semantic_resolver or SemanticResolver(
            metric_catalog=self.metric_catalog,
            llm_planner_gateway=self.llm_planner_gateway,
        )
        self.slot_validator = slot_validator or SlotValidator(required_slots=self.REQUIRED_SLOTS.copy())
        self.clarification_generator = clarification_generator or ClarificationGenerator()

    def plan(self, query: str, conversation_memory: dict | None = None) -> AnalyticsPlan:
        """把自然语言问题转换成结构化经营分析任务。

        关键边界：
        - 语义补强交给 `SemanticResolver`；
        - 最小可执行条件判断交给 `SlotValidator`；
        - 澄清问法生成交给 `ClarificationGenerator`；
        - Planner 负责把三者编排成最终 `AnalyticsPlan`。
        """

        resolution = self.semantic_resolver.resolve(
            query=query,
            conversation_memory=conversation_memory,
        )
        validation = self.slot_validator.validate(resolution.slots)
        clarification = self._build_clarification_if_needed(
            resolution_slots=resolution.slots,
            validation=validation,
            llm_question=resolution.llm_result.clarification_question if resolution.llm_result else None,
        )

        resolved_metric_definition = self.metric_catalog.resolve_metric(resolution.slots.get("metric"))
        return AnalyticsPlan(
            intent="business_analysis",
            slots=resolution.slots,
            required_slots=self.REQUIRED_SLOTS.copy(),
            missing_slots=validation.missing_slots,
            conflict_slots=validation.conflict_slots,
            is_executable=validation.is_executable,
            clarification_question=clarification.question if clarification is not None else None,
            clarification_target_slots=clarification.target_slots if clarification is not None else [],
            clarification_type=clarification.clarification_type if clarification is not None else None,
            clarification_reason=clarification.reason if clarification is not None else None,
            clarification_suggested_options=clarification.suggested_options if clarification is not None else [],
            data_source=resolved_metric_definition.data_source if resolved_metric_definition is not None else None,
            planning_source=resolution.planning_source,
            confidence=resolution.confidence,
            validation_reason=validation.validation_reason,
        )

    def _build_clarification_if_needed(
        self,
        *,
        resolution_slots: dict,
        validation: SlotValidationResult,
        llm_question: str | None,
    ) -> ClarificationPayload | None:
        """如有需要则构造澄清。"""

        if validation.is_executable:
            return None
        return self.clarification_generator.generate(
            missing_slots=validation.missing_slots,
            conflict_slots=validation.conflict_slots,
            current_slots=resolution_slots,
            validation_reason=validation.validation_reason,
            llm_question=llm_question,
        )
