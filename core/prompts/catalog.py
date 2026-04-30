"""项目级 Prompt Catalog。

Catalog 用来登记“项目里有哪些 prompt、它们服务什么业务、输出 Schema 是什么”。
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
)


def list_prompt_catalog() -> list[PromptCatalogEntry]:
    """返回当前项目登记的 Prompt 清单。"""

    return list(PROMPT_CATALOG)
