"""RAG 问答应用服务。

对外暴露的 RAG 问答接口，封装了 RAG Agent 和会话管理。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.agent.business_agents.rag_agent import RAGAgent
from core.agent.workflows.rag.state import RAGWorkflowOutcome
from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.task_run_repository import TaskRunRepository
from core.security.auth import UserContext

if TYPE_CHECKING:
    from core.rag.retrieval_chain import RetrievalChain
    from core.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)


class RAGService:
    """RAG 问答应用编排层。

    职责：
    - 持有 RAG Agent 实例
    - 持有会话仓储
    - 持有任务运行仓储
    - 对外暴露 submit_query / get_run_detail 等稳定业务接口
    - 不直接执行工作流，不直接操作 LangGraph 状态

    与 AnalyticsService 的区别：
    - RAG 不需要复杂的槽位管理
    - RAG 不需要 SQL 执行
    - RAG 更轻量，核心是检索 + 生成
    """

    def __init__(
        self,
        rag_agent: RAGAgent,
        conversation_repository: ConversationRepository,
        task_run_repository: TaskRunRepository,
    ) -> None:
        """初始化 RAG 服务。

        Args:
            rag_agent: RAG Agent 实例
            conversation_repository: 会话仓储
            task_run_repository: 任务运行仓储
        """

        self.rag_agent = rag_agent
        self.conversation_repository = conversation_repository
        self.task_run_repository = task_run_repository

    async def submit_query(
        self,
        query: str,
        user_context: UserContext,
        conversation_id: str | None = None,
        business_domain: str | None = None,
        knowledge_base_ids: list[str] | None = None,
    ) -> dict:
        """提交问答请求。

        Args:
            query: 用户问题
            user_context: 用户上下文
            conversation_id: 会话 ID（用于多轮对话）
            business_domain: 业务域过滤
            knowledge_base_ids: 知识库 ID 列表

        Returns:
            响应结果
        """

        run_id = f"rag_{user_context.user_id}_{id(query) % 100000:05d}"

        logger.info(
            f"[{run_id}] RAG 问答请求 | "
            f"user={user_context.user_id} | "
            f"query={query[:50]}... | "
            f"conversation={conversation_id}"
        )

        try:
            # 执行 RAG Agent
            result = await self.rag_agent.answer(
                query=query,
                user_context=user_context,
                conversation_id=conversation_id,
                trace_id=run_id,
                business_domain=business_domain,
                knowledge_base_ids=knowledge_base_ids,
                run_id=run_id,
            )

            # 记录会话消息
            if conversation_id:
                self._save_conversation_message(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    query=query,
                    answer=result.get("answer", ""),
                    user_id=user_context.user_id,
                )

            return {
                "data": {
                    "run_id": result.get("run_id"),
                    "query": result.get("query"),
                    "answer": result.get("answer"),
                    "citations": result.get("citations", []),
                    "outcome": result.get("outcome"),
                    "clarification": result.get("clarification"),
                    "processing_time_ms": result.get("processing_time_ms"),
                },
                "meta": build_response_meta(
                    is_async=False,
                    status=result.get("outcome", "unknown"),
                ),
            }

        except Exception as e:
            logger.error(f"[{run_id}] RAG 问答失败: {e}", exc_info=True)
            raise AppException(
                error_code=error_codes.INTERNAL_ERROR,
                message="处理问答请求失败",
                status_code=500,
                detail={"run_id": run_id, "reason": str(e)},
            )

    def get_run_detail(
        self,
        run_id: str,
        user_context: UserContext,
    ) -> dict:
        """获取运行详情。

        Args:
            run_id: 运行 ID
            user_context: 用户上下文

        Returns:
            运行详情
        """

        # 从任务仓储获取运行信息
        task_run = self.task_run_repository.get_by_run_id(run_id)

        if not task_run:
            raise AppException(
                error_code=error_codes.NOT_FOUND,
                message="指定的运行不存在",
                status_code=404,
                detail={"run_id": run_id},
            )

        # 检查权限
        if task_run.get("user_id") != user_context.user_id:
            raise AppException(
                error_code=error_codes.PERMISSION_DENIED,
                message="无权查看该运行详情",
                status_code=403,
            )

        return {
            "data": task_run,
            "meta": build_response_meta(),
        }

    def _save_conversation_message(
        self,
        conversation_id: str,
        run_id: str,
        query: str,
        answer: str,
        user_id: str,
    ) -> None:
        """保存会话消息。

        Args:
            conversation_id: 会话 ID
            run_id: 运行 ID
            query: 用户问题
            answer: 回答
            user_id: 用户 ID
        """

        try:
            self.conversation_repository.add_message(
                conversation_id=conversation_id,
                role="user",
                content=query,
                metadata={"run_id": run_id},
                user_id=user_id,
            )

            self.conversation_repository.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=answer,
                metadata={"run_id": run_id},
                user_id=user_id,
            )

        except Exception as e:
            logger.warning(f"保存会话消息失败: {e}")


def create_rag_service(
    retrieval_chain: "RetrievalChain",
    llm_gateway: "LLMGateway",
    conversation_repository: ConversationRepository,
    task_run_repository: TaskRunRepository,
) -> RAGService:
    """创建 RAG 服务的便捷工厂函数。

    Args:
        retrieval_chain: 检索链路
        llm_gateway: LLM 网关
        conversation_repository: 会话仓储
        task_run_repository: 任务运行仓储

    Returns:
        RAG 服务实例
    """

    # 创建 RAG Agent
    rag_agent = RAGAgent(
        retrieval_chain=retrieval_chain,
        llm_gateway=llm_gateway,
        min_retrieval_score=0.3,
        min_retrieval_count=1,
    )

    # 创建 RAG 服务
    return RAGService(
        rag_agent=rag_agent,
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
    )
