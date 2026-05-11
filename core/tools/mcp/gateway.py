"""
MCP (Model Context Protocol) Gateway 实现

MCP Gateway 提供：
1. 统一的 MCP 服务入口
2. 协议转换（A2A ↔ MCP）
3. 服务发现和负载均衡
4. 认证和限流
5. 请求路由

架构说明：
```
Agent --A2A--> MCP Gateway --MCP--> SQL MCP Server
                |
                +--MCP--> Report MCP Server
                |
                +--MCP--> Enterprise API MCP Server
```

使用示例：
```python
from core.tools.mcp import MCPGateway

gateway = MCPGateway()

# 注册 MCP 服务
gateway.register_mcp("sql", "http://sql-mcp-svc.default.svc.cluster.local:5001")
gateway.register_mcp("report", "http://report-mcp-svc.default.svc.cluster.local:5002")

# 调用 MCP
result = await gateway.call_mcp("sql", {
    "method": "execute_query",
    "params": {"sql": "SELECT * FROM sales"}
})
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

import asyncio
import logging
from typing import Any, Optional

from .schemas import MCPRequest, MCPResponse, MCPError

logger = logging.getLogger(__name__)


class MCPGateway:
    """
    MCP Gateway

    提供统一的 MCP 服务接入层，主要功能：
    1. MCP 服务注册和发现
    2. 请求路由和负载均衡
    3. 协议转换（A2A ↔ MCP）
    4. 认证和限流（预留接口）
    5. 监控和日志

    设计说明：
    - MCP Gateway 是可选的，如果 Agent 直接调用 MCP 服务也可以
    - Gateway 主要用于统一入口、监控和安全控制
    - 实际生产中，建议使用 K8s Ingress 或 Service Mesh 替代部分功能
    """

    def __init__(self, namespace: str = "default"):
        """
        初始化 MCP Gateway

        Args:
            namespace: K8s 命名空间
        """
        self.namespace = namespace
        self._mcp_services: dict[str, str] = {}

        logger.info(f"MCP Gateway initialized for namespace: {namespace}")

    def register_mcp(
        self,
        mcp_name: str,
        url: str,
        description: str = "",
    ) -> None:
        """
        注册 MCP 服务

        Args:
            mcp_name: MCP 服务名称（如 "sql", "report"）
            url: MCP 服务 URL
            description: 服务描述
        """
        self._mcp_services[mcp_name] = url
        logger.info(f"Registered MCP service: {mcp_name} -> {url}")

    def unregister_mcp(self, mcp_name: str) -> bool:
        """
        取消注册 MCP 服务

        Args:
            mcp_name: MCP 服务名称

        Returns:
            是否成功
        """
        if mcp_name in self._mcp_services:
            del self._mcp_services[mcp_name]
            logger.info(f"Unregistered MCP service: {mcp_name}")
            return True
        return False

    def get_mcp_url(self, mcp_name: str) -> str:
        """
        获取 MCP 服务 URL

        Args:
            mcp_name: MCP 服务名称

        Returns:
            服务 URL

        Raises:
            ValueError: MCP 服务未注册
        """
        if mcp_name not in self._mcp_services:
            raise ValueError(
                f"MCP service '{mcp_name}' not registered. "
                f"Available: {list(self._mcp_services.keys())}"
            )
        return self._mcp_services[mcp_name]

    def list_mcp_services(self) -> list[str]:
        """列出所有注册的 MCP 服务"""
        return list(self._mcp_services.keys())

    async def call_mcp(
        self,
        mcp_name: str,
        method: str,
        params: Optional[dict[str, Any]] = None,
        timeout: int = 300,
    ) -> MCPResponse:
        """
        调用 MCP 服务

        Args:
            mcp_name: MCP 服务名称
            method: MCP 方法名
            params: 方法参数
            timeout: 超时时间（秒）

        Returns:
            MCP 响应
        """
        url = self.get_mcp_url(mcp_name)
        endpoint = f"{url}/mcp/v1/call"

        request = MCPRequest(
            method=method,
            params=params or {},
        )

        try:
            import httpx
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    endpoint,
                    json=request.model_dump(mode="json"),
                )
                response.raise_for_status()
                return MCPResponse(**response.json())

        except Exception as e:
            logger.error(f"MCP call failed for {mcp_name}.{method}: {e}")
            return MCPResponse(
                success=False,
                error=MCPError(
                    code="MCP_CALL_FAILED",
                    message=str(e),
                )
            )

    async def batch_call_mcp(
        self,
        calls: list[tuple[str, str, Optional[dict]]],
    ) -> list[MCPResponse]:
        """
        批量调用多个 MCP 服务

        Args:
            calls: [(mcp_name, method, params), ...]

        Returns:
            响应列表
        """
        tasks = [
            self.call_mcp(mcp_name, method, params)
            for mcp_name, method, params in calls
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)


# ============================================================================
# MCP 到 A2A 的协议转换
# ============================================================================

class A2AToMCPS转换器:
    """
    A2A 到 MCP 的协议转换器

    将 A2A TaskEnvelope 转换为 MCPRequest
    将 MCPResponse 转换为 A2A ResultContract

    设计说明：
    - Agent 发送 A2A 格式的任务
    - Gateway 转换为 MCP 格式调用 MCP 服务
    - MCP 服务返回 MCPResponse
    - Gateway 转换为 A2A ResultContract 返回给 Agent
    """

    @staticmethod
    def task_envelope_to_mcp_request(
        task_id: str,
        trace_id: str,
        conversation_id: str,
        source_agent: str,
        target_agent: str,
        intent: str,
        message: dict,
        context: dict,
    ) -> MCPRequest:
        """
        将 TaskEnvelope 转换为 MCPRequest

        Args:
            task_id: 任务 ID
            trace_id: 链路追踪 ID
            conversation_id: 会话 ID
            source_agent: 来源 Agent
            target_agent: 目标 MCP 服务名
            intent: 意图
            message: 消息内容
            context: 上下文

        Returns:
            MCPRequest
        """
        return MCPRequest(
            method=intent,
            params={
                "task_id": task_id,
                "trace_id": trace_id,
                "conversation_id": conversation_id,
                "source_agent": source_agent,
                "message": message,
                "context": context,
            },
        )

    @staticmethod
    def mcp_response_to_result_contract(
        response: MCPResponse,
        task_id: str,
        trace_id: str,
        conversation_id: str,
    ) -> dict:
        """
        将 MCPResponse 转换为 ResultContract 格式

        Args:
            response: MCP 响应
            task_id: 任务 ID
            trace_id: 链路追踪 ID
            conversation_id: 会话 ID

        Returns:
            ResultContract 格式的字典
        """
        from ..a2a.schemas import TaskStatus

        if response.success:
            return {
                "task_id": task_id,
                "trace_id": trace_id,
                "conversation_id": conversation_id,
                "status": TaskStatus.SUCCEEDED.value,
                "result": response.result,
                "artifacts": response.artifacts or [],
            }
        else:
            return {
                "task_id": task_id,
                "trace_id": trace_id,
                "conversation_id": conversation_id,
                "status": TaskStatus.FAILED.value,
                "error": response.error.model_dump() if response.error else None,
            }
