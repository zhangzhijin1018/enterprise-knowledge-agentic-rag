"""
Analytics Agent Server - 基于 python_a2a 的标准化 A2A 服务

使用 python_a2a.A2AServer 实现标准的 A2A 协议：
1. 标准化 Agent Card
2. 标准化任务处理
3. K8s 部署支持

启动方式：
```bash
python -m apps.agents.analytics_agent_server

# 或
uvicorn apps.agents.analytics_agent_server:app --host 0.0.0.0 --port 6002
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
# Analytics Agent Server
# ============================================================================

class AnalyticsAgentServer(A2AServer):
    """
    Analytics Agent A2A 服务器

    使用 python_a2a 标准的 A2AServer 实现，
    提供经营数据分析能力。
    """

    name = "analytics-agent"
    version = "1.0.0"
    description = "经营分析 Agent - 支持发电量、收入、成本等指标查询和分析"

    def __init__(self, **kwargs):
        """初始化 Analytics Agent Server"""
        # 获取服务 URL
        host = os.environ.get("ANALYTICS_AGENT_HOST", "0.0.0.0")
        port = os.environ.get("ANALYTICS_AGENT_PORT", "6002")
        url = os.environ.get("A2A_AGENT_URL", f"http://{host}:{port}")

        # 创建 Agent Card
        agent_card = AgentCard(
            name=self.name,
            description=self.description,
            url=url,
            version=self.version,
            skills=[
                AgentSkill(
                    id="business_analysis",
                    name="经营分析",
                    description="发电量、收入、成本等经营指标分析",
                    tags=["analytics", "business", "metrics"],
                ),
                AgentSkill(
                    id="sql_query",
                    name="SQL 查询",
                    description="结构化数据 SQL 查询",
                    tags=["sql", "data"],
                ),
                AgentSkill(
                    id="trend_analysis",
                    name="趋势分析",
                    description="同比、环比趋势分析",
                    tags=["trend", "yoy", "mom"],
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

        logger.info(f"Analytics Agent Server 初始化完成，URL: {url}")

    def handle_task(self, task):
        """
        处理 A2A 任务（参考 agent_learn 示例）

        Args:
            task: A2A Task 对象

        Returns:
            处理后的 Task 对象
        """
        logger.info(f"[Analytics Agent] 收到 A2A 任务: {task}")

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
            output_mode = metadata.get("output_mode", "lite")
            need_sql_explain = metadata.get("need_sql_explain", False)

            from core.security.auth import UserContext
            user_context = UserContext(
                user_id=user_id,
                user_role=user_role,
                department_code=department_code,
            )

            # 3. 调用 Analytics Service
            import asyncio

            async def _process():
                service = await self._get_analytics_service()
                result = await service.analyze(
                    query=query,
                    user_context=user_context,
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                    output_mode=output_mode,
                    need_sql_explain=need_sql_explain,
                )
                return result

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(_process())
            finally:
                loop.close()

            # 4. 处理结果
            conclusion = result.get("conclusion", "")
            answer = result.get("answer", "抱歉，无法生成分析结果。")
            response_text = conclusion if conclusion else answer

            # 5. 设置 artifacts
            task.artifacts = [{
                "parts": [{"type": "text", "text": response_text}]
            }]
            task.status = TaskStatus(state=TaskState.COMPLETED)

            logger.info(f"[Analytics Agent] 任务处理完成")
            return task

        except Exception as e:
            logger.error(f"[Analytics Agent] 处理失败: {e}", exc_info=True)
            task.artifacts = [{
                "parts": [{"type": "text", "text": f"处理失败: {str(e)}"}]
            }]
            task.status = TaskStatus(state=TaskState.COMPLETED)
            return task

    async def _get_analytics_service(self):
        """获取 Analytics Service 实例"""
        if not hasattr(self, "_analytics_service") or self._analytics_service is None:
            from core.services.analytics_service import AnalyticsService
            from core.analytics.llm_content_generator import LLMContentGenerator
            from core.analytics.schema_registry import SchemaRegistry
            from core.analytics.metric_catalog import MetricCatalog

            schema_registry = SchemaRegistry()
            metric_catalog = MetricCatalog()
            llm_generator = LLMContentGenerator()
            self._analytics_service = AnalyticsService(
                schema_registry=schema_registry,
                metric_catalog=metric_catalog,
                llm_generator=llm_generator,
            )
        return self._analytics_service


# ============================================================================
# Agent Server 启动入口
# ============================================================================

def create_a2a_app():
    """
    创建 A2A 应用（参考 agent_learn 风格）

    直接使用 python_a2a.run_server 启动，无需额外 FastAPI 封装。
    """
    # 创建 A2A Server
    a2a_server = AnalyticsAgentServer()

    # 获取端口配置
    port = int(os.environ.get("ANALYTICS_AGENT_PORT", "6002"))
    host = os.environ.get("ANALYTICS_AGENT_HOST", "0.0.0.0")

    logger.info(f"Analytics Agent Server 初始化完成")
    logger.info(f"A2A 端点: http://{host}:{port}/a2a")
    logger.info(f"Agent Card: {a2a_server.agent_card.name}")

    # 使用 run_server 启动（参考 agent_learn）
    from python_a2a import run_server
    run_server(a2a_server, host=host, port=port)


# 主入口
if __name__ == "__main__":
    create_a2a_app()
