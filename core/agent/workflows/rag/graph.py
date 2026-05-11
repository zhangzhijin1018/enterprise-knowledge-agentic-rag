"""RAG Agent LangGraph StateGraph。

定义 RAG 智能问答流程的状态图结构。
"""

from __future__ import annotations

import logging
from typing import Annotated

from langgraph.graph import StateGraph, END

from core.agent.workflows.rag.state import (
    RAGWorkflowState,
    RAGWorkflowStage,
    RAGWorkflowOutcome,
)
from core.agent.workflows.rag.nodes import RAGWorkflowNodes

logger = logging.getLogger(__name__)


def create_rag_graph(
    nodes: RAGWorkflowNodes,
) -> StateGraph:
    """创建 RAG Agent StateGraph。

    状态流转：
    START → entry → understand → retrieve → evaluate → generate → finish → END
                         ↓                         ↓
                    (clarify)              (insufficient)

    Args:
        nodes: RAG 工作流节点集合

    Returns:
        编译后的 StateGraph
    """

    # 定义状态图
    graph = StateGraph(RAGWorkflowState)

    # 添加节点
    graph.add_node("entry", nodes.rag_entry)
    graph.add_node("understand", nodes.rag_understand)
    graph.add_node("retrieve", nodes.rag_retrieve)
    graph.add_node("evaluate", nodes.rag_evaluate)
    graph.add_node("generate", nodes.rag_generate)
    graph.add_node("finish", nodes.rag_finish)

    # 设置入口节点
    graph.set_entry_point("entry")

    # 添加边
    graph.add_edge("entry", "understand")
    graph.add_edge("understand", "retrieve")

    # 条件边：评估节点根据结果决定下一步
    graph.add_conditional_edges(
        "evaluate",
        _route_after_evaluate,
        {
            "continue": "generate",
            "insufficient": "generate",  # 不足时仍生成，使用默认回答
            "clarify": END,  # 需要澄清时结束，后续由澄清流程处理
            "fail": END,  # 失败时结束
        }
    )

    graph.add_edge("retrieve", "evaluate")
    graph.add_edge("generate", "finish")
    graph.add_edge("finish", END)

    # 编译图
    return graph.compile()


def _route_after_evaluate(state: RAGWorkflowState) -> str:
    """评估节点的条件路由。

    根据评估结果决定下一步：
    - continue: 检索结果足够，继续生成答案
    - insufficient: 检索结果不足，但仍生成答案（使用默认回答）
    - clarify: 需要澄清，结束当前流程
    - fail: 失败，结束流程

    Args:
        state: 当前状态

    Returns:
        下一个节点名称
    """

    outcome = state.get("outcome", RAGWorkflowOutcome.CONTINUE.value)

    if outcome == RAGWorkflowOutcome.CONTINUE.value:
        return "continue"
    elif outcome == RAGWorkflowOutcome.INSUFFICIENT.value:
        logger.warning(f"[{state.get('run_id', 'unknown')}] 检索结果不足，继续生成答案")
        return "insufficient"
    elif outcome == RAGWorkflowOutcome.CLARIFY.value:
        logger.info(f"[{state.get('run_id', 'unknown')}] 需要澄清")
        return "clarify"
    elif outcome == RAGWorkflowOutcome.FAIL.value:
        logger.error(f"[{state.get('run_id', 'unknown')}] 流程失败")
        return "fail"
    else:
        logger.warning(f"[{state.get('run_id', 'unknown')}] 未知 outcome: {outcome}")
        return "fail"


def run_rag_workflow(
    graph: StateGraph,
    initial_state: RAGWorkflowState,
    thread_id: str | None = None,
) -> RAGWorkflowState:
    """运行 RAG 工作流。

    Args:
        graph: 编译后的 StateGraph
        initial_state: 初始状态
        thread_id: 线程 ID，用于多轮对话状态保持

    Returns:
        最终状态
    """

    run_id = initial_state.get("run_id", "unknown")
    query = initial_state.get("query", "")

    logger.info(f"[{run_id}] 开始运行 RAG 工作流 | query={query[:50]}...")

    # 构建配置
    config = {}
    if thread_id:
        config["configurable"] = {"thread_id": thread_id}

    try:
        # 执行工作流
        result = graph.invoke(initial_state, config=config)

        logger.info(
            f"[{run_id}] RAG 工作流完成 | "
            f"outcome={result.get('outcome')} | "
            f"stage={result.get('current_stage')}"
        )

        return result

    except Exception as e:
        logger.error(f"[{run_id}] RAG 工作流执行异常: {e}", exc_info=True)

        # 返回带有错误信息的状态
        return {
            **initial_state,
            "outcome": RAGWorkflowOutcome.FAIL.value,
            "error": str(e),
        }
