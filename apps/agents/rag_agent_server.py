"""
RAG Agent Server - 基于 python_a2a 的标准化 A2A 服务

使用 python_a2a.A2AServer 实现标准的 A2A 协议：
1. 标准化 Agent Card
2. 标准化任务处理
3. K8s 部署支持

启动方式：
```bash
python -m apps.agents.rag_agent_server
# 或
uvicorn apps.agents.rag_agent_server:app --host 0.0.0.0 --port 6001
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

from python_a2a import A2AServer, AgentCard, AgentSkill, TaskStatus, TaskState

logger = logging.getLogger(__name__)


# ============================================================================
# FastAPI 应用（仅 A2A 协议）
# ============================================================================

class RAGAgentServer(A2AServer):
    """
    RAG Agent A2A 服务器

    使用 python_a2a 标准的 A2AServer 实现，
    提供知识库问答能力。
    """

    name = "rag-agent"
    version = "1.0.0"
    description = "RAG 知识库问答 Agent - 支持安全生产、规章制度、设备运维等领域问答"

    def __init__(self, **kwargs):
        """初始化 RAG Agent Server"""
        # 获取服务 URL（K8s 环境变量或默认）
        host = os.environ.get("RAG_AGENT_HOST", "0.0.0.0")
        port = os.environ.get("RAG_AGENT_PORT", "6001")
        url = os.environ.get("A2A_AGENT_URL", f"http://{host}:{port}")

        # 创建 Agent Card
        agent_card = AgentCard(
            name=self.name,
            description=self.description,
            url=url,
            version=self.version,
            skills=[
                AgentSkill(
                    id="rag_qa",
                    name="RAG 问答",
                    description="基于知识库的智能问答",
                    tags=["qa", "knowledge", "rag"],
                ),
                AgentSkill(
                    id="safety_qa",
                    name="安全生产问答",
                    description="安全生产规程和注意事项问答",
                    tags=["safety", "operation"],
                ),
                AgentSkill(
                    id="policy_qa",
                    name="制度政策问答",
                    description="集团制度政策查询和解读",
                    tags=["policy", "regulation"],
                ),
            ],
            capabilities={
                "streaming": True,
                "pushNotifications": False,
                "stateTransitionHistory": False,
            },
        )

        # 调用父类初始化
        super().__init__(
            agent_card=agent_card,
            **kwargs,
        )

        logger.info(f"RAG Agent Server 初始化完成，URL: {url}")

    async def handle_task(self, task):
        """
        处理 A2A 任务（支持 SSE 进度推送）

        Args:
            task: A2A Task 对象

        Returns:
            处理后的 Task 对象
        """
        from python_a2a import TaskStatus, TaskState

        logger.info(f"[RAG Agent] 收到 A2A 任务: {task}")

        # 获取 run_id（用于 SSE 推送）
        run_id = task.id or f"rag_{uuid.uuid4().hex[:12]}"
        sse_tracker = None

        try:
            # 1. 提取消息内容
            query = (task.message or {}).get("content", {}).get("text", "")

            if not query:
                task.artifacts = [{
                    "parts": [{"type": "text", "text": "请提供有效的问题。"}]
                }]
                task.status = TaskStatus(state=TaskState.COMPLETED)
                return task

            # 2. 提取用户上下文
            metadata = task.metadata or {}
            user_id = metadata.get("user_id", "anonymous")
            user_role = metadata.get("user_role", "user")
            department_code = metadata.get("department_code")
            trace_id = metadata.get("trace_id")
            conversation_id = metadata.get("conversation_id")
            business_domain = metadata.get("business_domain", "rag")

            # 3. 初始化 SSE tracker（推送进度）
            from core.common.sse_progress import RedisSSEProgressTracker, get_redis_pool

            try:
                pool = await get_redis_pool()
                workflow_steps = [
                    {"key": "understand_query", "label": "理解问题"},
                    {"key": "retrieve", "label": "检索知识库"},
                    {"key": "generate_answer", "label": "生成答案"},
                ]
                sse_tracker = RedisSSEProgressTracker(
                    run_id=run_id,
                    steps=workflow_steps,
                    redis_pool=pool,
                )
                await sse_tracker.__aenter__()
                await sse_tracker.step("understand_query")
            except Exception as e:
                logger.warning(f"RAG SSE tracker 初始化失败: {e}")
                sse_tracker = None

            from core.security.auth import UserContext
            user_context = UserContext(
                user_id=user_id,
                user_role=user_role,
                department_code=department_code,
            )

            # 4. 调用 RAG Agent
            agent = await self._get_rag_agent()

            # 推送检索阶段
            if sse_tracker:
                await sse_tracker.step("retrieve")

            result = await agent.answer(
                query=query,
                user_context=user_context,
                conversation_id=conversation_id,
                trace_id=trace_id,
                business_domain=business_domain,
            )

            # 推送生成答案阶段
            if sse_tracker:
                await sse_tracker.step("generate_answer")

            # 5. 处理结果
            answer = result.get("answer", "抱歉，无法生成回答。")
            outcome = result.get("outcome", "unknown")

            if outcome == "clarification_needed":
                clarification = result.get("clarification", {})
                clarification_text = "\n".join(clarification.get("questions", []))
                response_text = f"需要更多信息：\n{clarification_text}"
            else:
                response_text = answer

            # 推送完成
            if sse_tracker:
                await sse_tracker.finish(result={
                    "answer": response_text,
                    "outcome": outcome,
                    "citations": result.get("citations", []),
                })

            # 6. 设置 artifacts
            task.artifacts = [{
                "parts": [{"type": "text", "text": response_text}]
            }]
            task.status = TaskStatus(state=TaskState.COMPLETED)

            logger.info(f"[RAG Agent] 任务处理完成")
            return task

        except Exception as e:
            logger.error(f"[RAG Agent] 处理失败: {e}", exc_info=True)

            # 推送错误
            if sse_tracker:
                try:
                    await sse_tracker.error("RAG_ERROR", str(e))
                except Exception:
                    pass

            task.artifacts = [{
                "parts": [{"type": "text", "text": f"处理失败: {str(e)}"}]
            }]
            task.status = TaskStatus(state=TaskState.COMPLETED)
            return task
        finally:
            # 清理 SSE tracker
            if sse_tracker:
                try:
                    await sse_tracker.__aexit__(None, None, None)
                except Exception:
                    pass

    async def _get_rag_agent(self):
        """获取 RAG Agent 实例"""
        if not hasattr(self, "_rag_agent") or self._rag_agent is None:
            from core.agent.business_agents.rag_agent import RAGAgent
            from core.rag.retrieval_chain import RetrievalChain
            from core.llm.gateway import LLMGateway

            retrieval_chain = RetrievalChain()
            llm_gateway = LLMGateway()
            self._rag_agent = RAGAgent(
                retrieval_chain=retrieval_chain,
                llm_gateway=llm_gateway,
            )
        return self._rag_agent


# ============================================================================
# Agent Server 启动入口
# ============================================================================

def create_a2a_app():
    """
    创建 A2A 应用（参考 agent_learn 风格）

    直接使用 python_a2a.run_server 启动，无需额外 FastAPI 封装。
    """
    # 创建 A2A Server
    a2a_server = RAGAgentServer()

    # 获取端口配置
    port = int(os.environ.get("RAG_AGENT_PORT", "6001"))
    host = os.environ.get("RAG_AGENT_HOST", "0.0.0.0")

    logger.info(f"RAG Agent Server 初始化完成")
    logger.info(f"A2A 端点: http://{host}:{port}/a2a")
    logger.info(f"Agent Card: {a2a_server.agent_card.name}")

    # 使用 run_server 启动（参考 agent_learn）
    from python_a2a import run_server
    run_server(a2a_server, host=host, port=port)


# 主入口
if __name__ == "__main__":
    create_a2a_app()
