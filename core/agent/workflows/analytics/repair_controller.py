"""经营分析 ReAct Repair/Replan 能力。

当复杂分析（decomposed 模式）的 SQL 执行失败时，
使用 ReAct 子循环尝试修复意图或重新规划。

关键设计原则：
1. Repair 是"局部 ReAct"，只在 SQL 执行失败时触发
2. Repair 不允许生成新 SQL，只能修改意图参数
3. Replan 是完整的重新规划，但必须经过 Validator 校验
4. 所有修复操作必须记录到 repair_history 供审计
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.analytics.intent.schema import AnalyticsIntent, IntentValidationResult
from core.analytics.intent.validator import AnalyticsIntentValidator
from core.config.settings import Settings, get_settings
from core.llm import LLMGateway, LLMMessage, OpenAICompatibleLLMGateway
from core.prompts import PromptRegistry, PromptRenderer


class RepairAction(Enum):
    """Repair 可执行的动作枚举。"""

    # 放宽时间范围（从精确日期改为月/季度）
    RELAX_TIME_RANGE = "relax_time_range"
    # 简化分组维度（移除高基数维度）
    SIMPLIFY_GROUP_BY = "simplify_group_by"
    # 降低 top_n 上限
    REDUCE_TOP_N = "reduce_top_n"
    # 移除同比/环比分析
    REMOVE_COMPARE = "remove_compare"
    # 标记需要澄清
    REQUEST_CLARIFICATION = "request_clarification"
    # 无法修复，需要回退
    CANNOT_REPAIR = "cannot_repair"


@dataclass
class RepairResult:
    """Repair 操作结果。"""

    action: RepairAction
    # 修复后的意图（如果 action 不是 CANNOT_REPAIR）
    repaired_intent: AnalyticsIntent | None = None
    # 修复说明
    explanation: str = ""
    # 是否需要用户澄清
    need_clarification: bool = False
    # 澄清问题
    clarification_question: str | None = None
    # 建议的选项列表
    suggested_options: list[dict] = field(default_factory=list)


@dataclass
class ReplanResult:
    """Replan 操作结果。"""

    # 重新规划的意图
    new_intent: AnalyticsIntent | None = None
    # 是否成功重新规划
    success: bool = False
    # 重新规划说明
    explanation: str = ""
    # 需要澄清
    need_clarification: bool = False


class AnalyticsRepairController:
    """经营分析 SQL 执行失败时的 Repair/Replan 控制器。

    工作流程：
    1. SQL 执行失败时，根据错误类型判断是否可以修复
    2. 如果可以修复，使用 LLM 分析失败原因并生成修复意图
    3. 修复意图经过 Validator 校验后，使用修复后的意图重新执行
    4. 如果无法修复，返回澄清请求或标记失败
    """

    def __init__(
        self,
        *,
        intent_validator: AnalyticsIntentValidator | None = None,
        llm_gateway: LLMGateway | None = None,
        prompt_registry: PromptRegistry | None = None,
        prompt_renderer: PromptRenderer | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.intent_validator = intent_validator or AnalyticsIntentValidator()
        self.settings = settings or get_settings()
        self.llm_gateway = llm_gateway or OpenAICompatibleLLMGateway(settings=self.settings)
        self.prompt_registry = prompt_registry or PromptRegistry()
        self.prompt_renderer = prompt_renderer or PromptRenderer()

        # Repair 历史记录
        self._repair_history: list[dict] = []

    def repair(
        self,
        *,
        original_intent: AnalyticsIntent,
        error_message: str,
        error_type: str,
        max_repair_attempts: int = 2,
    ) -> RepairResult:
        """尝试修复意图以解决 SQL 执行错误。

        Args:
            original_intent: 原始用户意图
            error_message: 错误信息
            error_type: 错误类型（如 "timeout", "no_data", "syntax_error"）
            max_repair_attempts: 最大修复尝试次数

        Returns:
            RepairResult: 修复结果
        """

        # 分类错误类型
        repair_strategy = self._classify_error(error_type, error_message)

        if repair_strategy == "cannot_repair":
            return RepairResult(
                action=RepairAction.CANNOT_REPAIR,
                explanation=f"错误类型 '{error_type}' 无法自动修复",
            )

        # 调用 LLM 生成修复意图
        return self._llm_repair(
            original_intent=original_intent,
            error_message=error_message,
            error_type=error_type,
            max_attempts=max_repair_attempts,
        )

    def replan(
        self,
        *,
        original_intent: AnalyticsIntent,
        error_message: str,
        conversation_memory: dict | None = None,
    ) -> ReplanResult:
        """完整重新规划。

        当 Repair 失败时，使用完整 ReAct 子循环重新规划意图。
        """

        system_template = self.prompt_registry.load("analytics/repair_replan_system")
        user_template = self.prompt_registry.load("analytics/repair_replan_user")

        messages = [
            LLMMessage(role="system", content=self.prompt_renderer.render(system_template, {})),
            LLMMessage(
                role="user",
                content=self.prompt_renderer.render(
                    user_template,
                    {
                        "original_intent": original_intent.model_dump(mode="json"),
                        "error_message": error_message,
                        "conversation_memory": conversation_memory or {},
                    },
                ),
            ),
        ]

        try:
            response = self.llm_gateway.chat(
                messages=messages,
                model=self.settings.llm_model_name,
                temperature=0.3,  # 使用低温度保证确定性
            )

            # 解析 LLM 响应
            return self._parse_replan_response(response, original_intent)

        except Exception as exc:
            self._record_repair(
                action="replan",
                success=False,
                error=str(exc),
            )
            return ReplanResult(
                success=False,
                explanation=f"重新规划失败：{str(exc)}",
                need_clarification=True,
            )

    def _classify_error(self, error_type: str, error_message: str) -> str:
        """分类错误类型并决定修复策略。"""

        # 可以修复的错误类型
        repairable_errors = {
            "timeout": "relax_time_range",
            "no_data": "simplify_query",
            "too_many_rows": "reduce_top_n",
            "syntax_error": "request_clarification",
        }

        for key, strategy in repairable_errors.items():
            if key in error_type.lower() or key in error_message.lower():
                return strategy

        # 权限/安全错误不能修复
        if any(
            keyword in error_message.lower()
            for keyword in ["permission", "denied", "forbidden", "access"]
        ):
            return "cannot_repair"

        # 默认返回需要澄清
        return "request_clarification"

    def _llm_repair(
        self,
        *,
        original_intent: AnalyticsIntent,
        error_message: str,
        error_type: str,
        max_attempts: int = 2,
    ) -> RepairResult:
        """使用 LLM 生成修复意图。"""

        system_template = self.prompt_registry.load("analytics/repair_system")
        user_template = self.prompt_registry.load("analytics/repair_user")

        messages = [
            LLMMessage(role="system", content=self.prompt_renderer.render(system_template, {})),
            LLMMessage(
                role="user",
                content=self.prompt_renderer.render(
                    user_template,
                    {
                        "original_intent": original_intent.model_dump(mode="json"),
                        "error_message": error_message,
                        "error_type": error_type,
                        "max_attempts": max_attempts,
                    },
                ),
            ),
        ]

        for attempt in range(1, max_attempts + 1):
            try:
                response = self.llm_gateway.chat(
                    messages=messages,
                    model=self.settings.llm_model_name,
                    temperature=0.2,  # 低温度保证确定性
                )

                # 解析 LLM 响应并构建修复意图
                repair_result = self._parse_repair_response(response, original_intent)

                # 校验修复后的意图
                if repair_result.repaired_intent:
                    validation_result = self.intent_validator.validate(
                        repair_result.repaired_intent
                    )
                    if validation_result.valid and not validation_result.need_clarification:
                        self._record_repair(
                            action=repair_result.action.value,
                            success=True,
                            error=error_message,
                        )
                        return repair_result
                    else:
                        # 校验不通过，返回澄清
                        return RepairResult(
                            action=RepairAction.REQUEST_CLARIFICATION,
                            explanation="修复后的意图需要用户确认",
                            need_clarification=True,
                            clarification_question="修复后的意图需要您的确认。",
                            suggested_options=validation_result.suggested_options or [],
                        )

                return repair_result

            except Exception as exc:
                if attempt >= max_attempts:
                    self._record_repair(
                        action="llm_repair",
                        success=False,
                        error=str(exc),
                    )
                    return RepairResult(
                        action=RepairAction.CANNOT_REPAIR,
                        explanation=f"修复失败：{str(exc)}",
                    )
                time.sleep(0.5)

        return RepairResult(
            action=RepairAction.CANNOT_REPAIR,
            explanation="达到最大修复尝试次数",
        )

    def _parse_repair_response(
        self, response: str, original_intent: AnalyticsIntent
    ) -> RepairResult:
        """解析 LLM 修复响应。"""

        # 简单解析 - 实际应该使用 structured output
        response_lower = response.lower()

        # 根据响应关键词决定修复动作
        if "relax" in response_lower or "放宽" in response:
            return self._create_relaxed_intent(original_intent)
        elif "simplify" in response_lower or "简化" in response:
            return self._create_simplified_intent(original_intent)
        elif "reduce" in response_lower or "减少" in response:
            return self._create_reduced_intent(original_intent)
        elif "clarify" in response_lower or "澄清" in response:
            return RepairResult(
                action=RepairAction.REQUEST_CLARIFICATION,
                explanation="需要用户澄清",
                need_clarification=True,
                clarification_question="请提供更具体的信息",
            )
        else:
            return RepairResult(
                action=RepairAction.CANNOT_REPAIR,
                explanation="无法确定修复策略",
            )

    def _parse_replan_response(
        self, response: str, original_intent: AnalyticsIntent
    ) -> ReplanResult:
        """解析 LLM 重新规划响应。"""

        # 这里应该使用 structured output 解析
        # 暂时返回无法重新规划
        return ReplanResult(
            success=False,
            explanation="重新规划需要用户提供更多信息",
            need_clarification=True,
        )

    def _create_relaxed_intent(self, original: AnalyticsIntent) -> RepairResult:
        """创建放宽时间范围的修复意图。"""

        from copy import deepcopy
        from core.analytics.intent.schema import TimeRangeType

        repaired = deepcopy(original)

        # 如果是绝对时间，改为相对时间
        if repaired.time_range and hasattr(repaired.time_range, "type"):
            repaired.time_range.type = TimeRangeType.RELATIVE
            repaired.time_range.value = "近三个月"
            repaired.time_range.raw_text = "近三个月"

        return RepairResult(
            action=RepairAction.RELAX_TIME_RANGE,
            repaired_intent=repaired,
            explanation="已将时间范围从精确日期放宽为近三个月",
        )

    def _create_simplified_intent(self, original: AnalyticsIntent) -> RepairResult:
        """创建简化分组维度的修复意图。"""

        from copy import deepcopy

        repaired = deepcopy(original)

        # 简化 group_by
        if repaired.group_by and repaired.group_by not in ["month", "region"]:
            repaired.group_by = "region"

        # 移除 compare_target
        repaired.compare_target = None

        return RepairResult(
            action=RepairAction.SIMPLIFY_GROUP_BY,
            repaired_intent=repaired,
            explanation="已简化分组维度，移除了同比/环比分析",
        )

    def _create_reduced_intent(self, original: AnalyticsIntent) -> RepairResult:
        """创建减少 top_n 的修复意图。"""

        from copy import deepcopy

        repaired = deepcopy(original)

        # 减少 top_n
        if repaired.top_n and repaired.top_n > 10:
            repaired.top_n = 10

        return RepairResult(
            action=RepairAction.REDUCE_TOP_N,
            repaired_intent=repaired,
            explanation="已减少返回行数上限",
        )

    def _record_repair(
        self,
        *,
        action: str,
        success: bool,
        error: str | None = None,
    ) -> None:
        """记录修复历史。"""

        self._repair_history.append(
            {
                "action": action,
                "success": success,
                "error": error,
                "timestamp": time.time(),
            }
        )

    def get_repair_history(self) -> list[dict]:
        """获取修复历史。"""

        return list(self._repair_history)
