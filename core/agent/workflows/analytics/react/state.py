"""Analytics 局部 ReAct Planning 状态模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReactActionRecord(BaseModel):
    """ReAct 单步动作摘要。"""

    # 第几步，从 1 开始，方便调试 max_steps 是否生效。
    step: int = Field(description="步骤序号")
    # 允许工具白名单中的动作名称，或 finish。
    action: str = Field(description="动作名称")
    # 轻量动作输入。不能包含 SQL 或状态写入指令。
    action_input: dict[str, Any] = Field(default_factory=dict, description="动作输入")


class ReactObservationRecord(BaseModel):
    """ReAct 单步观察摘要。"""

    # 对应步骤序号。
    step: int = Field(description="步骤序号")
    # 对应动作名称。
    action: str = Field(description="动作名称")
    # 工具返回的轻量观察结果。
    observation: dict[str, Any] = Field(default_factory=dict, description="观察结果")


class ReactPlanCandidate(BaseModel):
    """ReAct 最终规划候选。"""

    # 候选槽位。最终仍需交给 AnalyticsPlanner / SlotValidator 校验。
    slots: dict[str, Any] = Field(default_factory=dict, description="候选槽位")
    # LLM 对候选规划的置信度。
    confidence: float = Field(default=0.0, description="候选规划置信度")
    # 简短原因，仅用于调试和观测，不作为权威业务状态。
    reason: str = Field(default="", description="候选规划原因")


class ReactStepOutput(BaseModel):
    """LLM 单步结构化输出。"""

    # thought 只保存轻量摘要，不保存完整长推理链。
    thought: str = Field(default="", description="规划思考摘要")
    # action 必须属于允许动作，planner 会再次做白名单校验。
    action: str = Field(default="finish", description="动作名称")
    # action_input 是工具参数，禁止包含 SQL 执行、状态更新、导出或审核指令。
    action_input: dict[str, Any] = Field(default_factory=dict, description="动作输入")
    # 当 action=finish 时，使用该字段承载最终候选规划。
    final_plan_candidate: ReactPlanCandidate | None = Field(
        default=None,
        description="最终规划候选",
    )
    # 停止原因，用于调试。
    stopped_reason: str = Field(default="", description="停止原因")


class AnalyticsReactState(BaseModel):
    """经营分析局部 ReAct Planning 子循环状态。

    这是 analytics_plan 节点内部的微观临时态：
    - 不直接写 task_run；
    - 不直接更新 slot_snapshot；
    - 不允许执行 SQL；
    - 最终只产出结构化 AnalyticsPlan 候选。
    """

    # 用户原始问题。
    query: str = Field(description="用户问题")
    # 会话记忆，供多轮承接使用。
    conversation_memory: dict[str, Any] = Field(default_factory=dict, description="会话记忆")
    # 每步 thought 摘要，不能保存大段推理链。
    thoughts: list[str] = Field(default_factory=list, description="思考摘要列表")
    # 每步动作摘要。
    actions: list[ReactActionRecord] = Field(default_factory=list, description="动作记录")
    # 每步观察摘要。
    observations: list[ReactObservationRecord] = Field(default_factory=list, description="观察记录")
    # 最终候选规划。
    final_plan_candidate: ReactPlanCandidate | None = Field(default=None, description="最终候选规划")
    # 最大步数，防止无限循环。
    max_steps: int = Field(default=3, description="最大 ReAct 步数")
    # 子循环停止原因。
    stopped_reason: str = Field(default="", description="停止原因")
