"""合同审查 Agent LangGraph StateGraph。

基于 LangGraph 的智能合同审查 Agent 状态图。

核心设计（重构版）：
1. ReAct 循环：entry → react_loop → reflect → (report/review) → finish
2. 支持 LLM 驱动的反思机制
3. 支持 Human Review 门控
4. 支持多轮对话和澄清机制

状态流转图：
```
START → entry
            │
            ├─ outcome=continue ──▶ react_loop ──▶ reflect ──▶ generate_report ──▶ finish
            │
            ├─ outcome=clarify ──▶ clarification ──▶ (用户补充信息) ──▶ entry
            │
            └─ outcome=fail ──▶ END
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging

from langgraph.graph import StateGraph, END

from core.agent.workflows.contract.state import (
    AgentThought,
    ContractWorkflowState,
    ContractWorkflowStage,
    ContractWorkflowOutcome,
)
from core.agent.workflows.contract.nodes import ContractWorkflowNodes

logger = logging.getLogger(__name__)


def create_contract_graph(
    nodes: ContractWorkflowNodes,
) -> StateGraph:
    """创建合同审查 Agent StateGraph。

    核心流程：
    entry → react_loop → reflect → (generate_report | human_review) → finish

    Args:
        nodes: 合同审查工作流节点集合

    Returns:
        编译后的 StateGraph
    """

    # 定义状态图
    graph = StateGraph(ContractWorkflowState)

    # ==================== 添加节点 ====================

    # 入口节点
    graph.add_node("entry", nodes.entry)

    # ReAct 循环节点
    graph.add_node("react_loop", nodes.react_loop)

    # 澄清节点（用于多轮对话：等待用户补充信息）
    graph.add_node("clarification", nodes.clarification)

    # 反思节点
    graph.add_node("reflect", nodes.reflect)

    # Human Review 节点
    graph.add_node("human_review", nodes.human_review)

    # 报告生成节点
    graph.add_node("generate_report", nodes.generate_report)

    # 结束节点
    graph.add_node("finish", nodes.finish)

    # ==================== 设置入口 ====================
    graph.set_entry_point("entry")

    # ==================== 边定义 ====================

    # entry 条件边：根据 outcome 决定下一步
    graph.add_conditional_edges(
        "entry",
        _entry_decision,
        {
            "react_loop": "react_loop",  # 正常执行
            "clarify": "clarification",  # 需要澄清
            "fail": END,                # 失败结束
        }
    )

    # react_loop → react_loop（继续循环）或 reflect（完成）
    graph.add_conditional_edges(
        "react_loop",
        _react_loop_decision,
        {
            "continue": "react_loop",  # 继续循环
            "reflect": "reflect",  # 进入反思
        }
    )

    # reflect → generate_report 或 human_review
    graph.add_conditional_edges(
        "reflect",
        _reflect_decision,
        {
            "generate_report": "generate_report",  # 直接生成报告
            "human_review": "human_review",  # 需要人工复核
        }
    )

    # human_review → generate_report
    graph.add_edge("human_review", "generate_report")

    # generate_report → finish
    graph.add_edge("generate_report", "finish")

    # clarification → entry（用户补充信息后重新验证）
    graph.add_edge("clarification", "entry")

    # finish → END
    graph.add_edge("finish", END)

    # 编译图
    compiled_graph = graph.compile()

    logger.info("合同审查 Agent Graph 编译完成")

    return compiled_graph


def _entry_decision(state: ContractWorkflowState) -> str:
    """entry 节点的条件决策。

    根据 entry 节点返回的 outcome 决定下一步：
    - "continue": 正常执行，进入 ReAct 循环
    - "clarify": 需要澄清，等待用户补充信息
    - "fail": 执行失败，直接结束

    这样设计的好处：
    - 缺参数时进入澄清机制，而非直接失败
    - 支持多轮对话：用户补充信息后重新验证
    """
    outcome = state.get("outcome", "")

    if outcome == ContractWorkflowOutcome.CLARIFY.value:
        return "clarify"
    elif outcome == ContractWorkflowOutcome.FAIL.value:
        return "fail"
    else:
        return "react_loop"


def _react_loop_decision(state: ContractWorkflowState) -> str:
    """ReAct 循环节点的条件决策。

    返回值：
    - "continue": 继续循环（还有工具未执行）
    - "reflect": 进入反思（所有工具已执行）
    """
    current_stage = state.get("current_stage", "")
    completed_tools = state.get("completed_tools", [])

    # 如果阶段已变为 reflect，进入反思
    if current_stage == ContractWorkflowStage.REFLECT.value:
        return "reflect"

    # 检查是否所有工具都已完成
    required_tools = ["parse_contract", "search_laws", "extract_clauses", "analyze_risk"]

    all_completed = all(tool in completed_tools for tool in required_tools)

    if all_completed:
        return "reflect"

    return "continue"


def _reflect_decision(state: ContractWorkflowState) -> str:
    """反思节点的条件决策。

    支持两种场景：
    1. 正常流程：反思完成 → 判断是否需要复核
    2. 恢复流程：复核已完成 → 直接生成报告

    返回值：
    - "generate_report": 直接生成报告
    - "human_review": 需要人工复核
    """
    outcome = state.get("outcome", "")
    agent_status = state.get("agent_status", "")
    human_review_status = state.get("human_review_status", "")
    human_review_decision = state.get("human_review_decision", "")

    # 【恢复场景】复核已完成（用户点击"生成报告"按钮后恢复）
    # 此时 human_review_status = "completed"，直接跳转到 generate_report
    if human_review_status == "completed":
        logger.info(
            f"[恢复流程] 复核已完成 | decision={human_review_decision} | "
            f"跳过 human_review 节点"
        )
        return "generate_report"

    # 如果是等待复核状态（正常流程中）
    if agent_status == AgentThought.WAITING_REVIEW.value:
        return "human_review"

    # 如果 outcome 是 REVIEW（正常流程中）
    if outcome == ContractWorkflowOutcome.REVIEW.value:
        return "human_review"

    # 默认生成报告
    return "generate_report"


def run_contract_workflow(
    graph: StateGraph,
    initial_state: ContractWorkflowState,
    thread_id: str | None = None,
) -> ContractWorkflowState:
    """运行合同审查工作流。

    Args:
        graph: 编译后的 StateGraph
        initial_state: 初始状态
        thread_id: 线程 ID（用于多轮对话）

    Returns:
        最终状态
    """

    run_id = initial_state.get("run_id", "unknown")
    contract_name = initial_state.get("contract_name", "")

    logger.info(
        f"[{run_id}] 开始运行合同审查工作流 | contract={contract_name}"
    )

    # 构建配置
    config = {}
    if thread_id:
        config["configurable"] = {"thread_id": thread_id}

    try:
        # 执行工作流
        result = graph.invoke(initial_state, config=config)

        logger.info(
            f"[{run_id}] 合同审查工作流完成 | "
            f"outcome={result.get('outcome')} | "
            f"stage={result.get('current_stage')} | "
            f"tools={len(result.get('completed_tools', []))}"
        )

        return result

    except Exception as e:
        logger.error(
            f"[{run_id}] 合同审查工作流执行异常: {e}",
            exc_info=True
        )

        # 返回带有错误信息的状态
        return {
            **initial_state,
            "outcome": ContractWorkflowOutcome.FAIL.value,
            "error": str(e),
        }


# ==================== 辅助函数 ====================


def visualize_workflow() -> str:
    """返回工作流的可视化描述（用于调试）。"""
    return """
    ┌─────────────────────────────────────────────────────────────────┐
    │                    Contract Review Agent                         │
    ├─────────────────────────────────────────────────────────────────┤
    │                                                                  │
    │  START ──▶ entry ──┬──▶ react_loop ──▶ reflect                  │
    │                    │                    │    │                   │
    │                    │                    │    └──▶ generate_report│
    │                    │                    │                       │
    │                    │                    └──▶ human_review       │
    │                    │                                             │
    │                    │                                              │
    │                    └──▶ clarification ◀──┘                       │
    │                         │                                        │
    │                         │ 用户补充信息后                          │
    │                         └───▶ entry ──┘                          │
    │                                                                  │
    ├─────────────────────────────────────────────────────────────────┤
    │  节点说明：                                                       │
    │  - entry: 入口验证（检查参数完整性）                            │
    │  - clarification: 澄清节点（等待用户补充信息）                   │
    │  - react_loop: ReAct 执行循环（解析→检索→抽取→分析）            │
    │  - reflect: LLM 驱动的反思校验                                   │
    │  - human_review: 人工复核（高风险项）                            │
    │  - generate_report: 生成审查报告                                │
    │  - finish: 结束                                                  │
    ├─────────────────────────────────────────────────────────────────┤
    │  澄清机制说明：                                                   │
    │  - 缺参数时自动进入澄清阶段，而非直接失败                       │
    │  - 澄清节点会设置 clarification_question 和 clarification_needed │
    │  - 用户补充信息后，重新进入 entry 重新验证                      │
    │  - 支持多轮澄清直到参数完整                                     │
    └─────────────────────────────────────────────────────────────────┘

    ReAct 循环内的工具执行顺序：
    1. parse_contract: 解析合同文档
    2. extract_clauses: 抽取合同条款（LLM 提取法律检索主题）
    3. search_laws: 检索相关法规
    4. search_templates: 检索标准模板
    5. search_history: 检索历史案例（为风险分析提供参考）
    6. analyze_risk: 分析合同风险（结合法规、模板、历史案例）

    反思机制：
    - 检查风险识别完整性
    - 检查法规依据充分性
    - 检查结论合理性
    - 如有问题触发补充检索或人工复核
    """
