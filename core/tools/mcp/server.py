"""
MCP (Model Context Protocol) Server 框架

MCP Server 用于实现 MCP 微服务，提供：
1. FastAPI 应用集成
2. 工具注册和路由
3. 认证和限流（预留）
4. 健康检查
5. 日志和监控

使用示例：
```python
from core.tools.mcp import MCPServer, mcp_tool

server = MCPServer(
    name="sql-mcp",
    version="1.0.0",
    description="SQL 查询服务"
)

@server.tool(name="execute_query", description="执行 SQL 查询")
async def execute_query(sql: str, params: dict = None):
    # 实现查询逻辑
    return {"rows": [], "count": 0}

# 启动服务
app = server.create_app()
uvicorn.run(app, host="0.0.0.0", port=5001)
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException

from .schemas import (
    MCPServerInfo,
    MCPServerStatus,
    MCPRequest,
    MCPResponse,
    MCPError,
    MCPTool,
    MCPToolList,
)

logger = logging.getLogger(__name__)


# 工具注册表类型
ToolHandler = Callable[..., Any]
ToolRegistry = dict[str, tuple[MCPTool, ToolHandler]]


class MCPServer:
    """
    MCP Server 框架

    提供 MCP 微服务的基础能力：
    1. 工具注册和管理
    2. 请求路由
    3. 健康检查
    4. FastAPI 集成

    设计说明：
    - 使用装饰器模式注册工具
    - 工具定义与实现分离
    - 支持同步和异步工具
    - 提供标准化错误处理
    """

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        description: str = "",
        max_concurrency: int = 10,
    ):
        """
        初始化 MCP Server

        Args:
            name: 服务名称
            version: 版本号
            description: 服务描述
            max_concurrency: 最大并发数
        """
        self.name = name
        self.version = version
        self.description = description
        self.max_concurrency = max_concurrency

        # 工具注册表
        self._tools: ToolRegistry = {}

        # 状态
        self._current_requests = 0
        self._start_time = time.time()
        self._running = False

        # FastAPI 应用
        self._app: Optional[FastAPI] = None

        logger.info(f"MCP Server initialized: {name} v{version}")

    # =========================================================================
    # 工具注册
    # =========================================================================

    def tool(
        self,
        name: str,
        description: str,
        input_schema: Optional[dict] = None,
        tags: Optional[list[str]] = None,
    ):
        """
        工具注册装饰器

        Args:
            name: 工具名称
            description: 工具描述
            input_schema: 输入参数定义
            tags: 标签列表

        Returns:
            装饰器函数

        Example:
            @server.tool(
                name="execute_query",
                description="执行 SQL 查询",
                input_schema={
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SQL 语句"},
                    },
                    "required": ["sql"]
                }
            )
            async def execute_query(sql: str):
                return {"rows": []}
        """
        def decorator(func: ToolHandler) -> ToolHandler:
            tool_def = MCPTool(
                name=name,
                description=description,
                input_schema=self._convert_to_mcp_params(input_schema or {}),
                tags=tags or [],
            )
            self._tools[name] = (tool_def, func)
            logger.info(f"Registered tool: {name}")
            return func

        return decorator

    def _convert_to_mcp_params(
        self, schema: dict
    ) -> "MCPParameters":
        """
        转换 JSON Schema 到 MCPParameters

        Args:
            schema: JSON Schema 定义

        Returns:
            MCPParameters
        """
        from .schemas import MCPParameters, MCPProperty

        properties = {}
        for prop_name, prop_def in schema.get("properties", {}).items():
            properties[prop_name] = MCPProperty(
                type=prop_def.get("type", "string"),
                description=prop_def.get("description"),
                default=prop_def.get("default"),
                enum=prop_def.get("enum", []),
            )

        return MCPParameters(
            type=schema.get("type", "object"),
            properties=properties,
            required=schema.get("required", []),
            additional_properties=schema.get("additionalProperties", False),
        )

    def register_tool(
        self,
        name: str,
        handler: ToolHandler,
        description: str = "",
        input_schema: Optional[dict] = None,
        tags: Optional[list[str]] = None,
    ) -> None:
        """
        手动注册工具

        适用于不想用装饰器的场景

        Args:
            name: 工具名称
            handler: 处理函数
            description: 工具描述
            input_schema: 输入参数定义
            tags: 标签列表
        """
        tool_def = MCPTool(
            name=name,
            description=description,
            input_schema=self._convert_to_mcp_params(input_schema or {}),
            tags=tags or [],
        )
        self._tools[name] = (tool_def, handler)
        logger.info(f"Manually registered tool: {name}")

    def list_tools(self) -> list[MCPTool]:
        """
        列出所有已注册的工具

        Returns:
            工具列表
        """
        return [tool_def for tool_def, _ in self._tools.values()]

    def get_tool(self, name: str) -> Optional[MCPTool]:
        """
        获取工具定义

        Args:
            name: 工具名称

        Returns:
            工具定义或 None
        """
        if name in self._tools:
            return self._tools[name][0]
        return None

    # =========================================================================
    # 请求处理
    # =========================================================================

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """
        处理 MCP 请求

        Args:
            request: MCP 请求

        Returns:
            MCP 响应
        """
        tool_name = request.method

        # 检查工具是否存在
        if tool_name not in self._tools:
            return MCPResponse(
                success=False,
                error=MCPError(
                    code="METHOD_NOT_FOUND",
                    message=f"Tool '{tool_name}' not found",
                ),
                request_id=request.request_id,
            )

        tool_def, handler = self._tools[tool_name]

        # 检查并发限制
        if self._current_requests >= self.max_concurrency:
            return MCPResponse(
                success=False,
                error=MCPError(
                    code="RATE_LIMITED",
                    message="Server is at max capacity",
                ),
                request_id=request.request_id,
            )

        self._current_requests += 1

        try:
            logger.info(f"Handling tool call: {tool_name}")

            # 调用工具
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**request.params)
            else:
                result = handler(**request.params)

            return MCPResponse(
                success=True,
                result=result,
                request_id=request.request_id,
            )

        except TypeError as e:
            # 参数错误
            logger.warning(f"Invalid parameters for {tool_name}: {e}")
            return MCPResponse(
                success=False,
                error=MCPError(
                    code="INVALID_PARAMS",
                    message=f"Invalid parameters: {str(e)}",
                    detail={"tool": tool_name},
                ),
                request_id=request.request_id,
            )

        except Exception as e:
            # 其他错误
            logger.error(f"Tool execution failed: {tool_name} - {e}")
            return MCPResponse(
                success=False,
                error=MCPError(
                    code="EXECUTION_ERROR",
                    message=str(e),
                    detail={"tool": tool_name},
                ),
                request_id=request.request_id,
            )

        finally:
            self._current_requests -= 1

    # =========================================================================
    # FastAPI 集成
    # =========================================================================

    def create_app(self) -> FastAPI:
        """
        创建 FastAPI 应用

        Returns:
            FastAPI 应用
        """
        app = FastAPI(
            title=f"{self.name} - MCP Server",
            description=self.description,
            version=self.version,
        )

        self._register_routes(app)
        self._running = True

        return app

    def _register_routes(self, app: FastAPI) -> None:
        """注册 MCP 路由"""

        @app.post("/mcp/v1/call")
        async def call_tool(request: MCPRequest) -> MCPResponse:
            """
            调用 MCP 工具

            POST /mcp/v1/call
            Body: MCPRequest
            Response: MCPResponse
            """
            return await self.handle_request(request)

        @app.get("/mcp/v1/tools")
        async def list_tools() -> MCPToolList:
            """
            获取工具列表

            GET /mcp/v1/tools
            Response: MCPToolList
            """
            return MCPToolList(
                tools=self.list_tools(),
                server_info={
                    "name": self.name,
                    "version": self.version,
                },
            )

        @app.get("/mcp/v1/tools/{tool_name}")
        async def get_tool(tool_name: str):
            """
            获取工具定义

            GET /mcp/v1/tools/{tool_name}
            Response: MCPTool
            """
            tool = self.get_tool(tool_name)
            if tool is None:
                raise HTTPException(status_code=404, detail="Tool not found")
            return tool

        @app.get("/mcp/v1/info")
        async def get_info() -> MCPServerInfo:
            """
            获取服务信息

            GET /mcp/v1/info
            Response: MCPServerInfo
            """
            return MCPServerInfo(
                name=self.name,
                version=self.version,
                description=self.description,
                capabilities=["tools", "streaming"],
                tools=[t.name for t in self.list_tools()],
            )

        @app.get("/mcp/v1/status")
        async def get_status() -> MCPServerStatus:
            """
            获取服务状态

            GET /mcp/v1/status
            Response: MCPServerStatus
            """
            return MCPServerStatus(
                server_name=self.name,
                status="online" if self._running else "offline",
                current_requests=self._current_requests,
                max_concurrency=self.max_concurrency,
                uptime_seconds=time.time() - self._start_time,
                last_heartbeat=datetime.now(),
            )

        @app.get("/mcp/v1/health")
        async def health_check():
            """
            健康检查

            GET /mcp/v1/health
            Response: {"status": "healthy"}
            """
            return {"status": "healthy"}

    # =========================================================================
    # 生命周期
    # =========================================================================

    async def start(self) -> None:
        """启动服务"""
        self._running = True
        logger.info(f"MCP Server started: {self.name}")

    async def stop(self) -> None:
        """停止服务"""
        self._running = False
        logger.info(f"MCP Server stopped: {self.name}")


# ============================================================================
# MCPParameters 导入
# ============================================================================

from .schemas import MCPParameters


# ============================================================================
# 便捷函数
# ============================================================================

def create_mcp_server(
    name: str,
    version: str = "1.0.0",
    description: str = "",
) -> MCPServer:
    """
    创建 MCP Server 的便捷函数

    Args:
        name: 服务名称
        version: 版本号
        description: 服务描述

    Returns:
        MCPServer 实例
    """
    return MCPServer(
        name=name,
        version=version,
        description=description,
    )
