"""经营分析 Planner 的 LLM fallback 适配层。

设计目标：
1. 不让 `analytics_planner.py` 直接耦合任何具体 LLM SDK；
2. 把“规则不足时，如何让 LLM 做结构化补强”收口到独立模块；
3. 即使当前没有真实 LLM 配置，也能返回清晰、可测试、可扩展的占位结构；
4. 明确限制：LLM 只能补强槽位，不允许直接从自然语言生成 SQL。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.agent.control_plane.analytics_llm_schemas import AnalyticsSlotFallbackOutput
from core.agent.control_plane.analytics_slot_fallback_validator import (
    AnalyticsSlotFallbackValidationError,
    AnalyticsSlotFallbackValidator,
)
from core.analytics.metric_catalog import MetricCatalog
from core.analytics.schema_registry import SchemaRegistry
from core.common.exceptions import AppException
from core.config.settings import Settings
from core.llm import LLMGateway, LLMMessage, OpenAICompatibleLLMGateway
from core.prompts import PromptRegistry, PromptRenderer


@dataclass(slots=True)
class LLMAnalyticsPlannerResult:
    """LLM fallback 结构化输出。

    注意：这里是 semantic_resolver 可消费的“安全摘要”，不是原始模型输出。
    原始模型响应必须先经过 Pydantic Schema 与 Validator，避免把 SQL、
    task_run_update、export/review 等越界字段带入后续业务链。
    """

    slots: dict = field(default_factory=dict)
    clarification_question: str | None = None
    clarification_target_slots: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "disabled"
    should_use: bool = False
    reason: str = ""


class LLMAnalyticsPlannerGateway:
    """经营分析 Planner 的 LLM fallback 网关。

    这一层是“LLM 访问边界”，不是业务执行器：
    - 业务代码不直接调用具体模型 SDK；
    - Prompt 通过 PromptRegistry 文件化管理；
    - 输出通过 Pydantic Schema 和 Validator 双重校验；
    - LLM 只能补槽位，不能生成 SQL、不能更新 task_run、不能触发 review/export。
    """

    def __init__(
        self,
        *,
        settings: Settings,
        llm_gateway: LLMGateway | None = None,
        prompt_registry: PromptRegistry | None = None,
        prompt_renderer: PromptRenderer | None = None,
        output_validator: AnalyticsSlotFallbackValidator | None = None,
        metric_catalog: MetricCatalog | None = None,
        schema_registry: SchemaRegistry | None = None,
        planner_callable=None,
    ) -> None:
        self.settings = settings
        self.llm_gateway = llm_gateway
        self.prompt_registry = prompt_registry or PromptRegistry()
        self.prompt_renderer = prompt_renderer or PromptRenderer()
        self.metric_catalog = metric_catalog or MetricCatalog()
        self.schema_registry = schema_registry or SchemaRegistry(settings=settings)
        self.output_validator = output_validator or AnalyticsSlotFallbackValidator(
            metric_catalog=self.metric_catalog,
            schema_registry=self.schema_registry,
        )
        # planner_callable 是兼容旧测试和过渡期外部 adapter 的入口。
        # 新代码应优先注入 LLMGateway，而不是继续把模型调用包成散落 callable。
        self.planner_callable = planner_callable

    def enhance_slots(
        self,
        *,
        query: str,
        current_slots: dict,
        conversation_memory: dict | None,
    ) -> LLMAnalyticsPlannerResult:
        """尝试用 LLM 对规则结果做补强。

        这里永远不判断“是否可以执行 SQL”。最小可执行条件仍由本地 SlotValidator
        决定，避免 LLM 通过 should_use=true 越过 clarification。
        """

        if not self.settings.analytics_planner_enable_llm_fallback:
            return LLMAnalyticsPlannerResult(
                source="disabled",
                should_use=False,
                confidence=0.0,
            )

        if self.planner_callable is not None:
            return self._enhance_with_legacy_callable(
                query=query,
                current_slots=current_slots,
                conversation_memory=conversation_memory or {},
            )

        gateway = self._resolve_llm_gateway()
        if gateway is None:
            # 开关已打开但没有可用 Gateway 时，明确返回不可用原因。
            # 这样本地测试不需要真实 API Key，生产排查也能看到 fallback 未生效的原因。
            return LLMAnalyticsPlannerResult(
                source="llm_gateway_unavailable",
                should_use=False,
                confidence=0.0,
                reason="LLM fallback 已启用，但未配置可用 LLMGateway 或 LLM_API_KEY",
            )

        try:
            system_template = self.prompt_registry.load("analytics/slot_fallback_system")
            user_template = self.prompt_registry.load("analytics/slot_fallback_user")
            output = gateway.structured_output(
                messages=[
                    LLMMessage(role="system", content=self.prompt_renderer.render(system_template, {})),
                    LLMMessage(
                        role="user",
                        content=self.prompt_renderer.render(
                            user_template,
                            {
                                "query": query,
                                "current_slots": current_slots,
                                "conversation_memory": conversation_memory or {},
                                "allowed_slots": sorted(AnalyticsSlotFallbackValidator.ALLOWED_SLOT_KEYS),
                            },
                        ),
                    ),
                ],
                output_schema=AnalyticsSlotFallbackOutput,
                model=self.settings.analytics_planner_llm_model or self.settings.llm_model_name,
                timeout_seconds=self.settings.llm_timeout_seconds,
                metadata={
                    "component": "analytics_slot_fallback",
                    "prompt_name": "analytics/slot_fallback_user",
                    "prompt_version": "v1",
                },
            )
            safe_slots = self.output_validator.validate(output.slots)
        except (AppException, AnalyticsSlotFallbackValidationError, ValueError) as exc:
            return LLMAnalyticsPlannerResult(
                source="llm_fallback_failed",
                should_use=False,
                confidence=0.0,
                reason=str(exc),
            )

        return LLMAnalyticsPlannerResult(
            slots=safe_slots,
            clarification_question=output.clarification_question,
            clarification_target_slots=output.clarification_target_slots,
            confidence=output.confidence,
            source="llm_gateway",
            should_use=bool(output.should_use and safe_slots),
            reason=output.reason,
        )

    def _enhance_with_legacy_callable(
        self,
        *,
        query: str,
        current_slots: dict,
        conversation_memory: dict,
    ) -> LLMAnalyticsPlannerResult:
        """兼容旧 planner_callable，同时也执行统一 Validator。

        迁移期保留该入口是为了不破坏已有测试和外部 mock；
        但即便是 callable 返回的 dict，也必须通过同一套字段白名单。
        """

        raw_result = self.planner_callable(
            query=query,
            current_slots=current_slots,
            conversation_memory=conversation_memory,
        )
        if isinstance(raw_result, LLMAnalyticsPlannerResult):
            return self._validate_result(raw_result)

        # 允许注入简单 dict，便于测试时 mock。
        raw_dict: dict[str, Any] = raw_result if isinstance(raw_result, dict) else {}
        result = LLMAnalyticsPlannerResult(
            slots=raw_dict.get("slots", {}),
            clarification_question=raw_dict.get("clarification_question"),
            clarification_target_slots=raw_dict.get("clarification_target_slots", []),
            confidence=float(raw_dict.get("confidence", 0.0)),
            source=raw_dict.get("source", "adapter"),
            should_use=bool(raw_dict.get("should_use", False)),
            reason=raw_dict.get("reason", ""),
        )
        return self._validate_result(result)

    def _validate_result(self, result: LLMAnalyticsPlannerResult) -> LLMAnalyticsPlannerResult:
        """对任何来源的 fallback 输出做统一安全校验。"""

        if not result.should_use:
            return result
        try:
            safe_slots = self.output_validator.validate(result.slots)
        except AnalyticsSlotFallbackValidationError as exc:
            return LLMAnalyticsPlannerResult(
                source=f"{result.source}_validation_failed",
                should_use=False,
                confidence=0.0,
                reason=str(exc),
            )
        return LLMAnalyticsPlannerResult(
            slots=safe_slots,
            clarification_question=result.clarification_question,
            clarification_target_slots=result.clarification_target_slots,
            confidence=result.confidence,
            source=result.source,
            should_use=bool(safe_slots),
            reason=result.reason,
        )

    def _resolve_llm_gateway(self) -> LLMGateway | None:
        """解析可用的 LLMGateway。

        如果外部显式注入 Mock/真实 Gateway，则直接使用；
        如果未注入，则只有在 API Key 看起来已配置时才创建 OpenAI-compatible Gateway。
        这样单元测试和本地开发不会因为没有真实模型服务而失败。
        """

        if self.llm_gateway is not None:
            return self.llm_gateway
        if not self.settings.llm_api_key or self.settings.llm_api_key == "your-api-key":
            return None
        return OpenAICompatibleLLMGateway(settings=self.settings)
