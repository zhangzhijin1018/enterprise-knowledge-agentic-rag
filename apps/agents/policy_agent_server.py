"""
Policy Agent Server - 基于 python_a2a 的标准化 A2A 服务

使用 python_a2a.A2AServer 实现标准的 A2A 协议。

启动方式：
```bash
uvicorn apps.agents.policy_agent_server:app --host 0.0.0.0 --port 6004
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from python_a2a import A2AServer, AgentCard, AgentSkill, TaskStatus, TaskState

logger = logging.getLogger(__name__)


# ============================================================================
# Policy Agent Server
# ============================================================================

class PolicyAgentServer(A2AServer):
    """Policy Agent A2A 服务器"""

    name = "policy-agent"
    version = "1.0.0"
    description = "制度政策 Agent - 支持集团制度、政策、规程查询"

    def __init__(self, **kwargs):
        host = os.environ.get("POLICY_AGENT_HOST", "0.0.0.0")
        port = os.environ.get("POLICY_AGENT_PORT", "6004")
        url = os.environ.get("A2A_AGENT_URL", f"http://{host}:{port}")

        agent_card = AgentCard(
            name=self.name,
            description=self.description,
            url=url,
            version=self.version,
            skills=[
                AgentSkill(
                    id="policy_search",
                    name="政策查询",
                    description="集团制度和政策查询",
                    tags=["policy", "regulation"],
                ),
                AgentSkill(
                    id="procedure_search",
                    name="规程查询",
                    description="操作规程和管理规程查询",
                    tags=["procedure", "operation"],
                ),
            ],
            capabilities={"streaming": True},
        )

        super().__init__(
            agent_card=agent_card,
            **kwargs,
        )

        logger.info(f"Policy Agent Server 初始化完成，URL: {url}")

    def handle_task(self, task):
        """
        处理 A2A 任务

        Args:
            task: A2A Task 对象

        Returns:
            处理后的 Task 对象
        """
        logger.info(f"[Policy Agent] 收到 A2A 任务: {task}")

        try:
            # 1. 提取消息内容
            query = (task.message or {}).get("content", {}).get("text", "")

            if not query:
                task.artifacts = [{
                    "parts": [{"type": "text", "text": "请提供有效的问题。"}]
                }]
                task.status = TaskStatus(state=TaskState.COMPLETED)
                return task

            # 2. 提取元数据
            metadata = task.metadata or {}
            user_id = metadata.get("user_id", "anonymous")

            # 3. 处理请求
            response_text = (
                f"制度政策查询请求已接收。\n"
                f"用户: {user_id}\n"
                f"问题: {query}\n\n"
                f"注意: 制度政策功能正在开发中。"
            )

            # 4. 设置 artifacts
            task.artifacts = [{
                "parts": [{"type": "text", "text": response_text}]
            }]
            task.status = TaskStatus(state=TaskState.COMPLETED)

            logger.info(f"[Policy Agent] 任务处理完成")
            return task

        except Exception as e:
            logger.error(f"[Policy Agent] 处理失败: {e}", exc_info=True)
            task.artifacts = [{
                "parts": [{"type": "text", "text": f"处理失败: {str(e)}"}]
            }]
            task.status = TaskStatus(state=TaskState.COMPLETED)
            return task


# ============================================================================
# Agent Server 启动入口
# ============================================================================

def create_a2a_app():
    """
    创建 A2A 应用（参考 agent_learn 风格）

    直接使用 python_a2a.run_server 启动，无需额外 FastAPI 封装。
    """
    # 创建 A2A Server
    a2a_server = PolicyAgentServer()

    # 获取端口配置
    port = int(os.environ.get("POLICY_AGENT_PORT", "6004"))
    host = os.environ.get("POLICY_AGENT_HOST", "0.0.0.0")

    logger.info(f"Policy Agent Server 初始化完成")
    logger.info(f"A2A 端点: http://{host}:{port}/a2a")
    logger.info(f"Agent Card: {a2a_server.agent_card.name}")

    # 使用 run_server 启动（参考 agent_learn）
    from python_a2a import run_server
    run_server(a2a_server, host=host, port=port)


# 主入口
if __name__ == "__main__":
    create_a2a_app()
