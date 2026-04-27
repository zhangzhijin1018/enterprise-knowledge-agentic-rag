"""Agent 状态模型。

当前仅定义基础状态结构，便于后续 LangGraph 工作流和审计链路统一对接。
"""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """Agent 运行状态结构。

    使用结构化状态而不是散乱 dict，可以让后续路由、工具调用、人工复核和 Trace
    都围绕统一字段展开，降低流程扩展时的维护成本。
    """

    # 本次 Agent 运行唯一 ID，用于串联 Trace、工具调用和人工复核记录。
    run_id: str

    # 当前多轮会话 ID，用于把本轮执行与会话上下文绑定起来。
    conversation_id: str

    # 当前链路 Trace 标识，用于把 API 请求、任务运行和日志串成同一条链路。
    trace_id: str

    # 发起请求的用户 ID，用于权限校验和审计归属。
    user_id: int

    # 当前用户角色，例如普通员工、安全管理员、法务人员等。
    user_role: str

    # 用户原始问题或任务指令。
    query: str

    # 前端或上层业务给出的业务提示，例如 policy、analytics。
    business_hint: str

    # 路由结果，例如 policy_qa、safety_qa、business_analysis 等。
    route: str

    # 当前问题所属业务域，例如安全生产、经营分析、合同审查等。
    business_domain: str

    # 当前任务类型。第一阶段主要是 chat，后续会扩展到 contract_review、report_generation 等。
    task_type: str

    # 当前允许访问的知识库 ID 列表，用于前置权限过滤。
    knowledge_base_ids: list[str]

    # 前端带入的最近历史消息。
    # 当前阶段仅做上下文占位，不直接替代服务端持久化消息。
    history_messages: list[dict[str, Any]]

    # 检索得到的 chunk 列表。
    # 当前先用宽松类型占位，后续会替换为明确的检索结果模型。
    retrieved_chunks: list[dict[str, Any]]

    # 本次运行中的工具调用记录列表，用于执行追踪和审计。
    tool_calls: list[dict[str, Any]]

    # 当前任务风险等级，例如 low、medium、high。
    risk_level: str

    # 是否需要进入 Human Review。
    need_human_review: bool

    # 人工复核状态，例如 pending、approved、rejected。
    review_status: str

    # 最终回答内容。
    final_answer: str

    # 当前选中的业务专家。
    selected_agent: str

    # 当前选中的能力或执行入口。
    selected_capability: str

    # 统一子状态，便于前端展示细粒度进度。
    sub_status: str

    # 本轮回答引用结果。
    citations: list[dict[str, Any]]

    # 当前澄清事件 ID。
    clarification_id: str

    # 当前澄清问题文案。
    clarification_question: str

    # 当前需要补充的槽位列表。
    clarification_slots: list[str]

    # 当前运行状态，例如 running、completed、failed。
    status: str
