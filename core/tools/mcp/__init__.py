"""
MCP (Model Context Protocol) 模块

提供 MCP 微服务的完整实现，包括：
- schemas: 协议数据结构
- client: MCP 客户端（基于 python_a2a.mcp.MCPClient）
- sql_mcp_server: SQL 查询 MCP 服务
- report_mcp_server: 报告生成 MCP 服务
- gateway: MCP Gateway

使用示例（参考 agent_learn）：
```python
# Server 端启动
from core.tools.mcp.sql_mcp_server import mcp
from python_a2a.mcp import create_fastapi_app
import uvicorn

app = create_fastapi_app(mcp)
uvicorn.run(app, host="0.0.0.0", port=5001)

# Client 端调用
from core.tools.mcp import MCPClient

client = MCPClient("http://localhost:5001")
result = await client.call_tool("execute_sql_query", sql="SELECT 1")
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from .client import (
    MCPClient,
    MCPClientFactory,
    create_sql_mcp_client,
    create_report_mcp_client,
    create_enterprise_mcp_client,
    get_mcp_client_factory,
    get_langchain_tool,
    DEFAULT_MCP_ENDPOINTS,
)
from .gateway import A2AToMCPS转换器, MCPGateway
from .schemas import (
    MCPError,
    MCPErrorCode,
    MCPParameters,
    MCPProperty,
    MCPRequest,
    MCPResponse,
    MCPServerInfo,
    MCPServerStatus,
    MCPStreamEvent,
    MCPTool,
    MCPToolKind,
    MCPToolList,
)

__all__ = [
    # Client
    "MCPClient",
    "MCPClientFactory",
    "create_sql_mcp_client",
    "create_report_mcp_client",
    "create_enterprise_mcp_client",
    "get_mcp_client_factory",
    "get_langchain_tool",
    "DEFAULT_MCP_ENDPOINTS",

    # Gateway
    "MCPGateway",
    "A2AToMCPS转换器",

    # Schemas
    "MCPRequest",
    "MCPResponse",
    "MCPError",
    "MCPErrorCode",
    "MCPTool",
    "MCPToolList",
    "MCPToolKind",
    "MCPServerInfo",
    "MCPServerStatus",
    "MCPParameters",
    "MCPProperty",
    "MCPStreamEvent",
]
