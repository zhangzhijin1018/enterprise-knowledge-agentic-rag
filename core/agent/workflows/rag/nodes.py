"""RAG Agent 节点集合。

每个节点是一个独立的异步函数，接收 state，返回 state 更新。
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from core.agent.workflows.rag.state import (
    RAGWorkflowState,
    RAGWorkflowStage,
    RAGWorkflowOutcome,
)
from core.agent.workflows.rag.prompts import (
    build_answer_prompt,
    build_evaluation_prompt,
    SYSTEM_PROMPT,
)

if TYPE_CHECKING:
    from core.rag.retrieval_chain import RetrievalChain
    from core.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)


class RAGWorkflowNodes:
    """RAG Agent 工作流节点集合。

    节点设计原则：
    - 每个节点职责单一
    - 节点之间通过 state 传递数据
    - 错误处理统一在节点内
    - 使用异步函数便于集成

    节点列表：
    1. rag_entry - 入口节点
    2. rag_understand - 查询理解节点
    3. rag_retrieve - 检索节点
    4. rag_evaluate - 评估节点
    5. rag_generate - 生成节点
    6. rag_finish - 结束节点
    """

    def __init__(
        self,
        retrieval_chain: RetrievalChain,
        llm_gateway: LLMGateway,
        min_retrieval_score: float = 0.3,
        min_retrieval_count: int = 1,
    ) -> None:
        """初始化 RAG 工作流节点。

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

    # ==================== 节点定义 ====================

    async def rag_entry(self, state: RAGWorkflowState) -> dict:
        """入口节点。

        职责：
        - 初始化工作流上下文
        - 记录开始时间
        - 日志记录

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """

        start_time = time.time()
        run_id = state["run_id"]
        query = state["query"]

        logger.info(
            f"[{run_id}] RAG 工作流开始 | query={query[:50]}... | "
            f"user={state['user_id']} | role={state['user_role']}"
        )

        return {
            "current_stage": RAGWorkflowStage.RAG_ENTRY.value,
            "outcome": RAGWorkflowOutcome.CONTINUE.value,
        }

    async def rag_understand(self, state: RAGWorkflowState) -> dict:
        """查询理解节点。

        职责：
        - 解析用户查询
        - 确定检索范围
        - 补充过滤条件

        当前简化实现：
        - 直接使用原始 query
        - 不做复杂查询改写

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """

        run_id = state["run_id"]
        query = state["query"]

        logger.info(f"[{run_id}] 理解查询: {query[:50]}...")

        # 简化实现：直接使用原始 query
        query_rewritten = query

        # TODO: 未来可以实现：
        # 1. 查询改写（同义词扩展）
        # 2. 查询分解（多跳问答）
        # 3. 澄清检测

        return {
            "current_stage": RAGWorkflowStage.RAG_UNDERSTAND.value,
            "outcome": RAGWorkflowOutcome.CONTINUE.value,
            "query_rewritten": query_rewritten,
        }

    async def rag_retrieve(self, state: RAGWorkflowState) -> dict:
        """检索节点。

        职责：
        - 执行混合检索
        - 收集检索结果
        - 记录检索元数据

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """

        run_id = state["run_id"]
        query = state.get("query_rewritten") or state["query"]
        filters = state.get("filters", {})

        logger.info(f"[{run_id}] 执行检索 | query={query[:50]}...")

        try:
            # 执行检索
            result = self.retrieval_chain.retrieve(
                query_text=query,
                filters=filters,
            )

            chunks = result.get("chunks", [])
            context = result.get("context", "")
            citations = result.get("citations", [])
            metadata = result.get("metadata", {})

            logger.info(
                f"[{run_id}] 检索完成 | 召回 {len(chunks)} 条 | "
                f"context_len={len(context)}"
            )

            return {
                "current_stage": RAGWorkflowStage.RAG_RETRIEVE.value,
                "outcome": RAGWorkflowOutcome.CONTINUE.value,
                "retrieved_chunks": chunks,
                "context": context,
                "citations": citations,
                "retrieval_metadata": metadata,
            }

        except Exception as e:
            logger.error(f"[{run_id}] 检索失败: {e}", exc_info=True)
            return {
                "current_stage": RAGWorkflowStage.RAG_RETRIEVE.value,
                "outcome": RAGWorkflowOutcome.FAIL.value,
                "error": f"检索失败: {str(e)}",
            }

    async def rag_evaluate(self, state: RAGWorkflowState) -> dict:
        """评估节点。

        职责：
        - 检查检索结果是否足够
        - 评估答案质量信心度
        - 决定是否需要补充检索或使用默认回答

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """

        run_id = state["run_id"]
        chunks = state.get("retrieved_chunks", [])
        context = state.get("context", "")

        logger.info(f"[{run_id}] 评估检索结果 | count={len(chunks)}")

        # 评估逻辑
        evaluation = self._evaluate_retrieval(chunks, context)

        # 检查是否需要澄清
        if evaluation.get("need_clarification"):
            return {
                "current_stage": RAGWorkflowStage.RAG_EVALUATE.value,
                "outcome": RAGWorkflowOutcome.CLARIFY.value,
                "need_clarification": True,
                "clarification_message": evaluation.get("clarification_message"),
                "retrieval_evaluation": evaluation,
            }

        # 检查检索结果是否足够
        if not evaluation.get("sufficient"):
            return {
                "current_stage": RAGWorkflowStage.RAG_EVALUATE.value,
                "outcome": RAGWorkflowOutcome.INSUFFICIENT.value,
                "retrieval_evaluation": evaluation,
            }

        # 检索结果足够
        return {
            "current_stage": RAGWorkflowStage.RAG_EVALUATE.value,
            "outcome": RAGWorkflowOutcome.CONTINUE.value,
            "retrieval_evaluation": evaluation,
        }

    async def rag_generate(self, state: RAGWorkflowState) -> dict:
        """生成节点。

        职责：
        - 基于检索上下文生成答案
        - 添加引用标记
        - 返回带引用的答案

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """

        run_id = state["run_id"]
        query = state["query"]
        context = state.get("context", "")
        citations = state.get("citations", [])
        evaluation = state.get("retrieval_evaluation", {})

        logger.info(f"[{run_id}] 生成答案")

        try:
            # 检查是否有检索结果
            if not context:
                # 无检索结果，使用默认回答
                answer = self._generate_no_result_answer(query)
                answer_with_citations = answer
            else:
                # 有检索结果，生成答案
                answer, answer_with_citations = await self._generate_answer(
                    query=query,
                    context=context,
                    citations=citations,
                    evaluation=evaluation,
                )

            logger.info(f"[{run_id}] 答案生成完成 | answer_len={len(answer)}")

            return {
                "current_stage": RAGWorkflowStage.RAG_GENERATE.value,
                "outcome": RAGWorkflowOutcome.CONTINUE.value,
                "answer": answer,
                "answer_with_citations": answer_with_citations,
            }

        except Exception as e:
            logger.error(f"[{run_id}] 答案生成失败: {e}", exc_info=True)
            return {
                "current_stage": RAGWorkflowStage.RAG_GENERATE.value,
                "outcome": RAGWorkflowOutcome.FAIL.value,
                "error": f"答案生成失败: {str(e)}",
                "answer": "抱歉，生成答案时出现了问题，请稍后重试。",
                "answer_with_citations": "抱歉，生成答案时出现了问题，请稍后重试。",
            }

    async def rag_finish(self, state: RAGWorkflowState) -> dict:
        """结束节点。

        职责：
        - 记录完成状态
        - 组装最终响应
        - 记录处理时间

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """

        run_id = state["run_id"]
        answer = state.get("answer_with_citations", state.get("answer", ""))
        outcome = state.get("outcome", RAGWorkflowOutcome.FAIL.value)

        logger.info(
            f"[{run_id}] RAG 工作流完成 | outcome={outcome} | "
            f"answer_len={len(answer)}"
        )

        return {
            "current_stage": RAGWorkflowStage.RAG_FINISH.value,
            "outcome": outcome,
        }

    # ==================== 辅助方法 ====================

    def _evaluate_retrieval(
        self,
        chunks: list[dict],
        context: str,
    ) -> dict:
        """评估检索结果。

        Args:
            chunks: 检索到的 chunks
            context: 构造的上下文

        Returns:
            评估结果
        """

        evaluation = {
            "sufficient": False,
            "relevance_score": 0.0,
            "coverage_score": 0.0,
            "confidence_score": 0.0,
            "need_clarification": False,
            "clarification_message": None,
            "issues": [],
            "suggestions": [],
        }

        # 检查结果数量
        if len(chunks) < self.min_retrieval_count:
            evaluation["issues"].append(f"检索结果过少，仅找到 {len(chunks)} 条")
            evaluation["suggestions"].append("尝试使用更通用的关键词")
            return evaluation

        # 检查分数
        scores = [chunk.get("score", 0.0) for chunk in chunks]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        evaluation["relevance_score"] = avg_score
        evaluation["coverage_score"] = min(avg_score * 1.2, 1.0)  # 简单估算

        # 检查是否达到阈值
        if avg_score < self.min_retrieval_score:
            evaluation["issues"].append(
                f"检索结果相关性较低，平均分数 {avg_score:.2f}"
            )
            evaluation["suggestions"].append("检索结果可能不够准确")
            return evaluation

        # 结果足够
        evaluation["sufficient"] = True
        evaluation["confidence_score"] = avg_score

        return evaluation

    async def _generate_answer(
        self,
        query: str,
        context: str,
        citations: list[dict],
        evaluation: dict,
    ) -> tuple[str, str]:
        """生成答案。

        Args:
            query: 用户问题
            context: 检索上下文
            citations: 引用列表
            evaluation: 评估结果

        Returns:
            (原始答案, 带引用的答案)
        """

        # 构建 Prompt
        prompt = build_answer_prompt(query, context)

        # 调用 LLM
        response = await self.llm_gateway.agenerate(
            messages=[{"role": "system", "content": SYSTEM_PROMPT}],
            prompt=prompt,
        )

        answer = response.content if hasattr(response, "content") else str(response)

        # 添加引用
        answer_with_citations = self._add_citations_to_answer(answer, citations)

        return answer, answer_with_citations

    def _generate_no_result_answer(self, query: str) -> str:
        """生成无检索结果时的回答。

        Args:
            query: 用户问题

        Returns:
            回答文本
        """

        return """知识库中未找到与您问题相关的内容。

这可能是因为：
1. 相关文档尚未入库
2. 文档内容与问题的表述方式不同
3. 问题超出了当前知识库的范围

建议您：
1. 尝试使用不同的关键词描述您的问题
2. 联系知识库管理员确认相关文档是否已上传
3. 如果问题涉及最新政策或规定，建议查阅官方发布的最新文件
"""

    def _add_citations_to_answer(
        self,
        answer: str,
        citations: list[dict],
    ) -> str:
        """在答案中添加引用。

        Args:
            answer: 原始答案
            citations: 引用列表

        Returns:
            带引用的答案
        """

        if not citations:
            return answer

        citation_lines = ["\n\n---\n**参考来源：**\n"]

        for cite in citations[:10]:  # 最多显示 10 个引用
            source_parts = []

            # 章节标题
            if cite.get("section_title"):
                source_parts.append(cite["section_title"])

            # 页码
            if cite.get("page_start"):
                if cite.get("page_end") and cite["page_end"] != cite["page_start"]:
                    source_parts.append(f"第{cite['page_start']}-{cite['page_end']}页")
                else:
                    source_parts.append(f"第{cite['page_start']}页")

            source_str = " - ".join(source_parts) if source_parts else "未知来源"

            # 相关性
            score = cite.get("score", 0.0)
            score_str = f"相关性: {score:.0%}"

            citation_id = cite.get("citation_id", "[?]")
            citation_lines.append(
                f"{citation_id} {source_str} [{score_str}]"
            )

        return answer + "\n".join(citation_lines)
