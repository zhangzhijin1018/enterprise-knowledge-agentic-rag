"""RAG Agent 服务。

提供 RAG 智能问答的完整工作流封装。
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from core.agent.workflows.rag.state import (
    RAGWorkflowState,
    RAGWorkflowOutcome,
    create_initial_rag_state,
)
from core.agent.workflows.rag.nodes import RAGWorkflowNodes
from core.agent.workflows.rag.graph import create_rag_graph, run_rag_workflow
from core.common.exceptions import AppException

if TYPE_CHECKING:
    from core.rag.retrieval_chain import RetrievalChain
    from core.llm.gateway import LLMGateway
    from core.security.auth import UserContext

logger = logging.getLogger(__name__)


class RAGAgent:
    """RAG Agent 服务。

    职责：
    - 持有 RAG 工作流组件
    - 持有检索链路和 LLM 网关
    - 提供统一的问答接口
    - 管理会话状态

    使用方式：
    ```python
    agent = RAGAgent(
        retrieval_chain=retrieval_chain,
        llm_gateway=llm_gateway,
    )

    result = await agent.answer(
        query="安全生产注意事项有哪些？",
        user_context=user_context,
    )
    ```
    """

    def __init__(
        self,
        retrieval_chain: RetrievalChain,
        llm_gateway: LLMGateway,
        min_retrieval_score: float = 0.3,
        min_retrieval_count: int = 1,
    ) -> None:
        """初始化 RAG Agent。

        Args:
            retrieval_chain: 检索链路
            llm_gateway: LLM 网关
            min_retrieval_score: 最小检索分数阈值
            min_retrieval_count: 最小检索数量
        """

        self.retrieval_chain = retrieval_chain
        self.llm_gateway = llm_gateway
        self.min_retrieval_score = min_retrieval_score
        self.min_retrieval_count = min_retrieval_count

        # 创建工作流节点
        self._nodes = RAGWorkflowNodes(
            retrieval_chain=retrieval_chain,
            llm_gateway=llm_gateway,
            min_retrieval_score=min_retrieval_score,
            min_retrieval_count=min_retrieval_count,
        )

        # 创建工作流图
        self._graph = create_rag_graph(self._nodes)

    async def answer(
        self,
        query: str,
        user_context: UserContext,
        conversation_id: str | None = None,
        trace_id: str | None = None,
        business_domain: str | None = None,
        knowledge_base_ids: list[str] | None = None,
        run_id: str | None = None,
    ) -> dict:
        """回答用户问题。

        Args:
            query: 用户问题
            user_context: 用户上下文
            conversation_id: 会话 ID（用于多轮对话）
            trace_id: 追踪 ID
            business_domain: 业务域过滤
            knowledge_base_ids: 知识库 ID 列表
            run_id: 运行 ID（可选）

        Returns:
            回答结果，包含：
            - run_id: 运行 ID
            - query: 原始问题
            - answer: 答案（带引用）
            - citations: 引用列表
            - outcome: 处理结果
            - retrieved_chunks: 检索到的 chunks
            - processing_time_ms: 处理时间
        """

        start_time = time.time()

        # 生成 run_id
        if not run_id:
            import uuid
            run_id = f"rag_{uuid.uuid4().hex[:12]}"

        # 创建初始状态
        state = create_initial_rag_state(
            run_id=run_id,
            query=query,
            user_id=user_context.user_id,
            user_role=user_context.user_role or "user",
            trace_id=trace_id,
            conversation_id=conversation_id,
            business_domain=business_domain,
            knowledge_base_ids=knowledge_base_ids,
        )

        try:
            # 运行工作流
            result = await self._run_workflow(state)

            # 计算处理时间
            processing_time_ms = int((time.time() - start_time) * 1000)

            # 构建返回结果
            return self._build_response(result, processing_time_ms)

        except Exception as e:
            logger.error(f"[{run_id}] RAG Agent 执行异常: {e}", exc_info=True)
            processing_time_ms = int((time.time() - start_time) * 1000)

            return {
                "run_id": run_id,
                "query": query,
                "answer": "抱歉，处理您的问题时出现了错误，请稍后重试。",
                "citations": [],
                "outcome": RAGWorkflowOutcome.FAIL.value,
                "retrieved_chunks": [],
                "context": "",
                "processing_time_ms": processing_time_ms,
                "error": str(e),
            }

    async def _run_workflow(self, state: RAGWorkflowState) -> RAGWorkflowState:
        """运行工作流。

        Args:
            state: 初始状态

        Returns:
            最终状态
        """

        run_id = state.get("run_id", "unknown")
        query = state.get("query", "")

        logger.info(f"[{run_id}] 开始 RAG 工作流 | query={query[:50]}...")

        try:
            # 使用 asyncio 运行同步的 graph.invoke
            import asyncio

            result = await asyncio.to_thread(
                run_rag_workflow,
                self._graph,
                state,
            )

            return result

        except Exception as e:
            logger.error(f"[{run_id}] 工作流执行失败: {e}", exc_info=True)
            return {
                **state,
                "outcome": RAGWorkflowOutcome.FAIL.value,
                "error": str(e),
            }

    def _build_response(
        self,
        result: RAGWorkflowState,
        processing_time_ms: int,
    ) -> dict:
        """构建返回结果。

        Args:
            result: 工作流结果
            processing_time_ms: 处理时间

        Returns:
            标准化的响应
        """

        outcome = result.get("outcome", RAGWorkflowOutcome.FAIL.value)

        # 根据 outcome 构建响应
        response = {
            "run_id": result.get("run_id"),
            "trace_id": result.get("trace_id"),
            "query": result.get("query"),
            "answer": result.get("answer_with_citations") or result.get("answer", ""),
            "answer_raw": result.get("answer", ""),
            "citations": result.get("citations", []),
            "retrieved_chunks": result.get("retrieved_chunks", []),
            "context": result.get("context", ""),
            "outcome": outcome,
            "current_stage": result.get("current_stage"),
            "processing_time_ms": processing_time_ms,
        }

        # 处理澄清情况
        if result.get("need_clarification"):
            response["clarification"] = {
                "needed": True,
                "message": result.get("clarification_message"),
            }

        # 处理错误情况
        if result.get("error"):
            response["error"] = result.get("error")

        # 处理检索评估
        evaluation = result.get("retrieval_evaluation", {})
        if evaluation:
            response["evaluation"] = evaluation

        return response
