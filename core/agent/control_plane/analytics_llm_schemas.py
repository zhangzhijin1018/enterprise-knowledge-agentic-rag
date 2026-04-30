"""经营分析 LLM fallback 结构化输出 Schema。

本文件只定义 LLM 输出的“可接收形状”，不代表输出已经可信。
真实进入业务主链前，还必须经过 `AnalyticsSlotFallbackValidator` 做白名单与危险字段校验。
这样可以把三层边界拆开：
1. Prompt 约束模型“应该怎么答”；
2. Pydantic Schema 约束“必须是什么结构”；
3. Validator 约束“哪些字段真正允许进入业务计划”。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalyticsSlotFallbackOutput(BaseModel):
    """经营分析槽位补强 LLM 输出。

    该 Schema 明确限制 LLM fallback 的职责：只能补强槽位和澄清建议，
    不能生成 SQL、不能执行查询、不能更新 task_run，也不能触发导出或审核。
    """

    slots: dict[str, Any] = Field(
        default_factory=dict,
        description="LLM 建议补强的经营分析槽位，后续必须经过白名单 Validator 清洗",
    )
    clarification_question: str | None = Field(
        default=None,
        description="当槽位仍不确定时，LLM 可提供更自然的澄清问题文本",
    )
    clarification_target_slots: list[str] = Field(
        default_factory=list,
        description="澄清问题对应的目标槽位列表，例如 metric/time_range",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="LLM 对本次槽位补强建议的置信度，不能替代本地最小可执行校验",
    )
    should_use: bool = Field(
        default=False,
        description="LLM 是否建议使用本次补强结果；最终是否采用仍由本地规则和 Validator 决定",
    )
    reason: str = Field(
        default="",
        description="LLM 给出的简短原因，用于调试和审计摘要，不作为业务执行依据",
    )
