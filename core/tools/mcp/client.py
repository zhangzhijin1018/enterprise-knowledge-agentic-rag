"""
MCP (Model Context Protocol) Client 实现

使用 python_a2a.mcp.MCPClient 调用 MCP 服务。

使用示例（参考 agent_learn）：
```python
from core.tools.mcp import MCPClient

# 连接到 MCP 服务
client = MCPClient("http://localhost:5001")

# 获取可用工具
tools = await client.get_tools()

# 调用工具
result = await client.call_tool("execute_sql_query", sql="SELECT * FROM table")
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 导入 python_a2a MCPClient
try:
    from python_a2a.mcp import MCPClient as BaseMCPClient
    from python_a2a.langchain import to_langchain_tool
    HAS_PYTHON_A2A = True
except ImportError:
    HAS_PYTHON_A2A = False
    BaseMCPClient = None
    to_langchain_tool = None


# ============================================================================
# MCP Client 配置
# ============================================================================

# 默认 MCP 服务端点配置
DEFAULT_MCP_ENDPOINTS = {
    "sql-mcp": os.environ.get(
        "SQL_MCP_URL",
        "http://sql-mcp-svc.default.svc.cluster.local:5001"
    ),
    "report-mcp": os.environ.get(
        "REPORT_MCP_URL",
        "http://report-mcp-svc.default.svc.cluster.local:5002"
    ),
    "enterprise-mcp": os.environ.get(
        "ENTERPRISE_MCP_URL",
        "http://enterprise-mcp-svc.default.svc.cluster.local:5003"
    ),
}


# ============================================================================
# MCP Client 类（使用 python_a2a.mcp.MCPClient）
# ============================================================================

class MCPClient:
    """
    MCP 客户端

    使用 python_a2a.mcp.MCPClient 封装，提供：
    1. 工具发现
    2. 工具调用
    3. LangChain 工具转换
    4. K8s 环境变量覆盖

    使用示例：
    ```python
    client = MCPClient("http://localhost:5001")

    # 获取工具列表
    tools = await client.get_tools()

    # 调用工具
    result = await client.call_tool("execute_sql_query", sql="SELECT 1")

    # 转换为 LangChain 工具
    langchain_tool = to_langchain_tool("http://localhost:5001", "execute_sql_query")
    ```
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        name: str = "default",
    ):
        """
        初始化 MCP Client

        Args:
            base_url: MCP 服务基础 URL（可选，默认从配置读取）
            name: Client 名称
        """
        if not HAS_PYTHON_A2A:
            raise ImportError(
                "python_a2a 未安装。请运行: pip install python-a2a"
            )

        # 获取 URL
        if base_url is None:
            base_url = DEFAULT_MCP_ENDPOINTS.get(name)

        if not base_url:
            raise ValueError(f"MCP URL not provided for client: {name}")

        self.name = name
        self.base_url = base_url
        self._client = BaseMCPClient(base_url)

        logger.info(f"MCP Client initialized: {name} -> {base_url}")

    async def get_tools(self) -> list[dict]:
        """
        获取可用工具列表

        Returns:
            工具列表
        """
        try:
            tools = await self._client.get_tools()
            logger.info(f"[{self.name}] Found {len(tools)} tools")
            return tools
        except Exception as e:
            logger.error(f"[{self.name}] Failed to get tools: {e}")
            return []

    async def call_tool(self, tool_name: str, **kwargs) -> dict:
        """
        调用 MCP 工具

        Args:
            tool_name: 工具名称
            **kwargs: 工具参数

        Returns:
            调用结果
        """
        try:
            logger.info(f"[{self.name}] Calling tool: {tool_name}")
            logger.debug(f"[{self.name}] Arguments: {kwargs}")

            # 调用工具
            result = await self._client.call_tool(tool_name, **kwargs)

            # 解析结果（可能是 JSON 字符串）
            if isinstance(result, str):
                try:
                    return json.loads(result)
                except json.JSONDecodeError:
                    return {"status": "success", "data": result}
            return result

        except Exception as e:
            logger.error(f"[{self.name}] Tool call failed: {tool_name} - {e}")
            return {
                "status": "error",
                "message": str(e),
                "tool": tool_name,
            }

    async def close(self) -> None:
        """关闭连接"""
        try:
            await self._client.close()
        except Exception as e:
            logger.warning(f"[{self.name}] Close failed: {e}")


# ============================================================================
# LangChain 工具转换（参考 agent_learn）
# ============================================================================

def get_langchain_tool(mcp_url: str, tool_name: str):
    """
    获取 LangChain 工具

    Args:
        mcp_url: MCP 服务 URL
        tool_name: 工具名称

    Returns:
        LangChain 工具
    """
    if not HAS_PYTHON_A2A:
        raise ImportError(
            "python_a2a 未安装，无法使用 LangChain 集成"
        )

    return to_langchain_tool(mcp_url, tool_name)


# ============================================================================
# MCP Client 工厂
# ============================================================================

class MCPClientFactory:
    """
    MCP Client 工厂

    管理多个 MCP Client 实例。
    """

    def __init__(self):
        """初始化工厂"""
        self._clients: dict[str, MCPClient] = {}

    def get_client(self, name: str) -> MCPClient:
        """
        获取 MCP Client

        Args:
            name: Client 名称（sql-mcp, report-mcp, enterprise-mcp）

        Returns:
            MCPClient 实例
        """
        if name not in self._clients:
            self._clients[name] = MCPClient(name=name)
        return self._clients[name]

    async def close_all(self) -> None:
        """关闭所有 Client"""
        for name, client in self._clients.items():
            await client.close()
            logger.info(f"Closed MCP client: {name}")
        self._clients.clear()


# 全局 Client 工厂
_client_factory: MCPClientFactory | None = None


def get_mcp_client_factory() -> MCPClientFactory:
    """获取全局 MCP Client 工厂"""
    global _client_factory
    if _client_factory is None:
        _client_factory = MCPClientFactory()
    return _client_factory


# ============================================================================
# 便捷函数
# ============================================================================

def create_sql_mcp_client() -> MCPClient:
    """创建 SQL MCP Client"""
    return MCPClient(name="sql-mcp")


def create_report_mcp_client() -> MCPClient:
    """创建 Report MCP Client"""
    return MCPClient(name="report-mcp")


def create_enterprise_mcp_client() -> MCPClient:
    """创建 Enterprise MCP Client"""
    return MCPClient(name="enterprise-mcp")


# ============================================================================
# 使用示例
# ============================================================================

async def example_usage():
    """
    使用示例（参考 agent_learn/mcp_base/python_a2a/client_agent.py）
    """
    print("=" * 50)
    print("MCP Client 使用示例")
    print("=" * 50)

    # 创建 Client
    client = create_sql_mcp_client()

    try:
        # 1. 获取工具列表
        print("\n1. 获取可用工具:")
        tools = await client.get_tools()
        for tool in tools:
            print(f"  - {tool.get('name')}: {tool.get('description')}")

        # 2. 调用工具
        print("\n2. 调用 execute_sql_query:")
        result = await client.call_tool(
            "execute_sql_query",
            data_source="analytics-db",
            sql="SELECT * FROM analytics_metrics_daily LIMIT 5",
            row_limit=5
        )
        print(f"  结果: {result}")

        # 3. 健康检查
        print("\n3. 健康检查:")
        result = await client.call_tool("healthcheck")
        print(f"  结果: {result}")

    finally:
        await client.close()

    print("\n" + "=" * 50)


if __name__ == "__main__":
    # 运行示例
    asyncio.run(example_usage())
