"""RAG Agent 工作流状态定义。

定义 RAG 智能问答流程中的状态结构。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict


class RAGWorkflowStage(str, Enum):
    """RAG Agent 的微观执行阶段。

    这些值描述 RAG 内部当前走到哪个节点。
    """

    # 入口节点：做输入标准化、会话准备。
    RAG_ENTRY = "rag_entry"

    # 查询理解节点：解析用户问题，确定检索范围。
    RAG_UNDERSTAND = "rag_understand"

    # 检索节点：执行混合检索 + Rerank。
    RAG_RETRIEVE = "rag_retrieve"

    # 评估节点：评估检索结果是否足够。
    RAG_EVALUATE = "rag_evaluate"

    # 生成节点：基于检索上下文生成答案。
    RAG_GENERATE = "rag_generate"

    # 结束节点：组装最终响应。
    RAG_FINISH = "rag_finish"


class RAGWorkflowOutcome(str, Enum):
    """RAG Agent 的微观结果方向。

    表达"当前节点之后，workflow 应该往哪个方向继续走"。
    """

    # 继续向下执行。
    CONTINUE = "continue"

    # 检索结果不足，需要补充检索或使用默认回答。
    INSUFFICIENT = "insufficient"

    # 当前请求需要澄清。
    CLARIFY = "clarify"

    # 当前请求需要人工审核。
    REVIEW = "review"

    # Workflow 已顺利完成，可以收口输出。
    FINISH = "finish"

    # Workflow 已失败，不再继续执行。
    FAIL = "fail"


class RAGWorkflowState(TypedDict, total=False):
    """RAG Agent 微观工作流状态。

    字段分三类：
    1. 输入态字段：来自 API / Supervisor
    2. 中间态字段：只在 workflow 节点之间流转
    3. 输出态字段：用于最终响应、状态映射和性能观测

    设计原因：
    - RAG 相比经营分析简单，不需要复杂的槽位管理
    - 但仍需要清晰的阶段划分，便于监控和调试
    """

    # -------------------------
    # 链路标识
    # -------------------------

    # 本次运行的唯一 ID，用于日志和追踪。
    run_id: str

    # 用于关联更上层的调用链。
    trace_id: str

    # 用于多轮对话的会话 ID。
    conversation_id: str | None

    # -------------------------
    # 输入态字段
    # -------------------------

    # 用户原始问题。
    query: str

    # 改写后的问题（可选）。
    query_rewritten: str | None

    # 当前用户上下文。
    user_id: str
    user_role: str

    # 业务域过滤。
    business_domain: str | None

    # 知识库 ID 列表。
    knowledge_base_ids: list[str] | None

    # -------------------------
    # 中间态字段
    # -------------------------

    # 检索过滤器。
    filters: dict[str, Any]

    # 检索结果 chunks。
    retrieved_chunks: list[dict]

    # 构造的检索上下文。
    context: str

    # 引用信息。
    citations: list[dict]

    # 检索元数据。
    retrieval_metadata: dict[str, Any]

    # 检索结果评估结果。
    retrieval_evaluation: dict[str, Any]

    # -------------------------
    # 输出态字段
    # -------------------------

    # 生成的原始答案（不含引用）。
    answer: str

    # 带引用的答案。
    answer_with_citations: str

    # 是否需要澄清。
    need_clarification: bool

    # 澄清消息。
    clarification_message: str | None

    # 是否需要人工审核。
    need_human_review: bool

    # 当前工作流阶段。
    current_stage: str

    # 工作流结果。
    outcome: str

    # 错误信息（如果有）。
    error: str | None

    # 处理时间（毫秒）。
    processing_time_ms: int | None


def create_initial_rag_state(
    run_id: str,
    query: str,
    user_id: str,
    user_role: str = "user",
    trace_id: str | None = None,
    conversation_id: str | None = None,
    business_domain: str | None = None,
    knowledge_base_ids: list[str] | None = None,
) -> RAGWorkflowState:
    """创建初始 RAG 工作流状态。

    Args:
        run_id: 唯一运行 ID
        query: 用户问题
        user_id: 用户 ID
        user_role: 用户角色
        trace_id: 追踪 ID
        conversation_id: 会话 ID
        business_domain: 业务域
        knowledge_base_ids: 知识库 ID 列表

    Returns:
        初始化的状态字典
    """

    # 构建基础过滤器
    filters: dict[str, Any] = {}

    if business_domain:
        filters["business_domain"] = business_domain

    if knowledge_base_ids:
        filters["knowledge_base_id"] = knowledge_base_ids

    # 用户角色过滤
    if user_role:
        filters["allowed_role_codes"] = [user_role]

    return RAGWorkflowState(
        # 链路标识
        run_id=run_id,
        trace_id=trace_id or run_id,
        conversation_id=conversation_id,
        # 输入态
        query=query,
        query_rewritten=None,
        user_id=user_id,
        user_role=user_role,
        business_domain=business_domain,
        knowledge_base_ids=knowledge_base_ids,
        # 中间态
        filters=filters,
        retrieved_chunks=[],
        context="",
        citations=[],
        retrieval_metadata={},
        retrieval_evaluation={},
        # 输出态
        answer="",
        answer_with_citations="",
        need_clarification=False,
        clarification_message=None,
        need_human_review=False,
        current_stage=RAGWorkflowStage.RAG_ENTRY.value,
        outcome=RAGWorkflowOutcome.CONTINUE.value,
        error=None,
        processing_time_ms=None,
    )
