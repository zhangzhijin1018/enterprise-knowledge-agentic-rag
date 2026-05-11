"""
SQL MCP HTTP Server - SQL MCP 微服务化版本

使用 FastAPI 将 SQL MCP 暴露为独立 HTTP 服务，支持：
1. K8s 部署
2. 水平扩展
3. 独立监控和告警
4. 资源隔离

启动方式：
```bash
uvicorn apps.mcp.sql_server:app --host 0.0.0.0 --port 5001
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from core.analytics.schema_registry import SchemaRegistry
from core.tools.mcp.sql_mcp_contracts import (
    SQLHealthcheckRequest,
    SQLHealthcheckResponse,
    SQLReadQueryRequest,
    SQLReadQueryResponse,
)
from core.tools.mcp.sql_mcp_server import SQLMCPServer


# ============================================================================
# 全局实例（懒加载）
# ============================================================================

_schema_registry: SchemaRegistry | None = None
_sql_mcp_server: SQLMCPServer | None = None


def get_schema_registry() -> SchemaRegistry:
    """获取或创建 SchemaRegistry 实例"""
    global _schema_registry
    if _schema_registry is None:
        _schema_registry = SchemaRegistry()
    return _schema_registry


def get_sql_mcp_server() -> SQLMCPServer:
    """获取或创建 SQL MCP Server 实例"""
    global _sql_mcp_server
    if _sql_mcp_server is None:
        _sql_mcp_server = SQLMCPServer(schema_registry=get_schema_registry())
    return _sql_mcp_server


# ============================================================================
# FastAPI 应用
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    server = get_sql_mcp_server()
    yield
    # 关闭时清理资源（如果需要）


app = FastAPI(
    title="SQL MCP Server",
    description="SQL 查询微服务 - 支持数据源路由、只读查询、健康检查",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# MCP 协议端点（标准 MCP 接口）
# ============================================================================

@app.post("/mcp/v1/call")
async def mcp_call(request: SQLReadQueryRequest) -> dict:
    """
    MCP 标准调用接口

    支持两种调用方式：
    1. execute_readonly_query：执行只读 SQL 查询
    2. healthcheck：健康检查

    Args:
        request: MCP 请求

    Returns:
        MCP 响应

    Example:
        POST /mcp/v1/call
        {
            "method": "execute_readonly_query",
            "params": {
                "data_source": "local_analytics",
                "sql": "SELECT * FROM analytics_metrics_daily",
                "timeout_ms": 3000,
                "row_limit": 500
            }
        }
    """
    server = get_sql_mcp_server()

    if request.method == "execute_readonly_query":
        sql_request = SQLReadQueryRequest(**request.params)
        response = server.execute_readonly_query(sql_request)
        return {
            "success": True,
            "result": {
                "data_source": response.data_source,
                "db_type": response.db_type,
                "columns": response.columns,
                "rows": response.rows,
                "row_count": response.row_count,
                "latency_ms": response.latency_ms,
                "checked_sql": response.checked_sql,
            },
        }
    elif request.method == "healthcheck":
        health_request = SQLHealthcheckRequest(**request.params) if request.params else SQLHealthcheckRequest()
        response = server.healthcheck(health_request)
        return {
            "success": True,
            "result": {
                "healthy": response.healthy,
                "data_source": response.data_source,
                "db_type": response.db_type,
                "latency_ms": response.latency_ms,
            },
        }
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown method: {request.method}",
        )


@app.get("/mcp/v1/tools")
async def list_tools() -> dict:
    """
    获取支持的工具列表

    Returns:
        工具列表
    """
    return {
        "tools": [
            {
                "name": "execute_readonly_query",
                "description": "执行只读 SQL 查询",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "data_source": {
                            "type": "string",
                            "description": "数据源标识",
                        },
                        "sql": {
                            "type": "string",
                            "description": "SQL 查询语句",
                        },
                        "timeout_ms": {
                            "type": "integer",
                            "description": "超时时间（毫秒）",
                            "default": 3000,
                        },
                        "row_limit": {
                            "type": "integer",
                            "description": "最大返回行数",
                            "default": 500,
                        },
                    },
                    "required": ["data_source", "sql"],
                },
            },
            {
                "name": "healthcheck",
                "description": "健康检查",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "data_source": {
                            "type": "string",
                            "description": "数据源标识（可选）",
                        },
                    },
                },
            },
        ],
        "server_info": {
            "name": "sql-mcp",
            "version": "1.0.0",
        },
    }


@app.get("/mcp/v1/info")
async def get_info() -> dict:
    """
    获取服务信息

    Returns:
        服务信息
    """
    return {
        "name": "sql-mcp",
        "version": "1.0.0",
        "description": "SQL 查询微服务",
        "capabilities": ["execute_readonly_query", "healthcheck"],
        "tools": ["execute_readonly_query", "healthcheck"],
    }


@app.get("/mcp/v1/status")
async def get_status() -> dict:
    """
    获取服务状态

    Returns:
        服务状态
    """
    server = get_sql_mcp_server()
    health_response = server.healthcheck()

    return {
        "server_name": "sql-mcp",
        "status": "online" if health_response.healthy else "degraded",
        "current_requests": 0,  # 当前请求数（简单实现）
        "max_concurrency": 10,
        "uptime_seconds": 0,  # 简单实现，不追踪
        "last_heartbeat": health_response.latency_ms,
    }


@app.get("/mcp/v1/health")
async def health_check() -> dict:
    """
    健康检查

    Returns:
        健康状态
    """
    return {"status": "healthy"}


# ============================================================================
# 业务接口（简化版）
# ============================================================================

@app.post("/api/v1/query")
async def execute_query(request: SQLReadQueryRequest) -> SQLReadQueryResponse:
    """
    执行 SQL 查询（业务接口）

    Args:
        request: 查询请求

    Returns:
        查询结果

    Example:
        POST /api/v1/query
        {
            "data_source": "local_analytics",
            "sql": "SELECT * FROM analytics_metrics_daily",
            "timeout_ms": 3000,
            "row_limit": 500
        }
    """
    server = get_sql_mcp_server()
    return server.execute_readonly_query(request)


@app.get("/api/v1/health")
async def api_health_check() -> dict:
    """
    API 健康检查

    Returns:
        健康状态
    """
    return {"status": "healthy"}


# ============================================================================
# 主入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.mcp.sql_server:app",
        host="0.0.0.0",
        port=5001,
        reload=False,
    )
