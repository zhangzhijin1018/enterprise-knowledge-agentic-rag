"""项目级 Prompt Catalog。

Catalog 用来登记"项目里有哪些 prompt、它们服务什么业务、输出 Schema 是什么"。
当前 PromptRegistry 不强依赖 catalog，是为了保持加载逻辑简单；
但 catalog 可以被测试、代码审查和后续 PromptOps 治理复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PromptCatalogEntry:
    """Prompt 登记项。"""

    name: str
    domain: str
    purpose: str
    input_variables: list[str] = field(default_factory=list)
    output_schema: str | None = None
    risk_level: str = "low"
    owner: str = "platform-agent-team"
    version: str = "v1"


PROMPT_CATALOG: tuple[PromptCatalogEntry, ...] = (
    # -------------------------------------------------------------------------
    # 经营分析意图解析 Prompt（新版统一主链路）
    # -------------------------------------------------------------------------
    PromptCatalogEntry(
        name="analytics/intent_parser_system",
        domain="analytics",
        purpose="经营分析统一意图解析器的系统边界提示词，负责告诉模型它是什么角色、约束和输出格式",
        input_variables=[],
        output_schema="AnalyticsIntent",
        risk_level="medium",
    ),
    PromptCatalogEntry(
        name="analytics/intent_parser_user",
        domain="analytics",
        purpose="经营分析统一意图解析器的用户上下文提示词，负责提供指标目录、Schema 摘要、会话上下文和示例",
        input_variables=[
            "query",
            "conversation_memory",
            "metric_catalog_summary",
            "schema_registry_summary",
            "user_context_summary",
        ],
        output_schema="AnalyticsIntent",
        risk_level="medium",
    ),
    # -------------------------------------------------------------------------
    # 经营分析 ReAct Planning Prompt（旧版，作为 fallback/可选能力保留）
    # -------------------------------------------------------------------------
    PromptCatalogEntry(
        name="analytics/react_planner_system",
        domain="analytics",
        purpose="经营分析复杂问题局部 ReAct planner 的系统边界提示词",
        input_variables=[],
        output_schema="ReactStepOutput",
        risk_level="medium",
    ),
    PromptCatalogEntry(
        name="analytics/react_planner_user",
        domain="analytics",
        purpose="经营分析复杂问题局部 ReAct planner 的用户上下文提示词",
        input_variables=["query", "conversation_memory", "steps", "metric_names", "group_by_keys"],
        output_schema="ReactStepOutput",
        risk_level="medium",
    ),
    # -------------------------------------------------------------------------
    # 经营分析 Slot Fallback Prompt（旧版，作为 fallback/可选能力保留）
    # -------------------------------------------------------------------------
    PromptCatalogEntry(
        name="analytics/slot_fallback_system",
        domain="analytics",
        purpose="经营分析规则低置信时的槽位补强系统提示词",
        input_variables=[],
        output_schema="AnalyticsSlotFallbackOutput",
        risk_level="medium",
    ),
    PromptCatalogEntry(
        name="analytics/slot_fallback_user",
        domain="analytics",
        purpose="经营分析规则低置信时的槽位补强用户上下文提示词",
        input_variables=["query", "current_slots", "conversation_memory", "allowed_slots"],
        output_schema="AnalyticsSlotFallbackOutput",
        risk_level="medium",
    ),
    # -------------------------------------------------------------------------
    # 经营分析 Repair/Replan Prompt（可选，SQL 执行失败时的修复能力）
    # -------------------------------------------------------------------------
    PromptCatalogEntry(
        name="analytics/repair_system",
        domain="analytics",
        purpose="SQL 执行失败时的意图修复系统提示词",
        input_variables=[],
        output_schema="RepairResult",
        risk_level="low",
    ),
    PromptCatalogEntry(
        name="analytics/repair_user",
        domain="analytics",
        purpose="SQL 执行失败时的意图修复用户上下文提示词",
        input_variables=["original_intent", "error_message", "error_type", "max_attempts"],
        output_schema="RepairResult",
        risk_level="low",
    ),
    PromptCatalogEntry(
        name="analytics/repair_replan_system",
        domain="analytics",
        purpose="SQL 执行失败时的完整重新规划系统提示词",
        input_variables=[],
        output_schema="ReplanResult",
        risk_level="medium",
    ),
    PromptCatalogEntry(
        name="analytics/repair_replan_user",
        domain="analytics",
        purpose="SQL 执行失败时的完整重新规划用户上下文提示词",
        input_variables=["original_intent", "error_message", "conversation_memory"],
        output_schema="ReplanResult",
        risk_level="medium",
    ),
)


def list_prompt_catalog() -> list[PromptCatalogEntry]:
    """返回当前项目登记的 Prompt 清单。"""

    return list(PROMPT_CATALOG)
