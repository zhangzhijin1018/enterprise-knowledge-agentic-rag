"""
Report MCP HTTP Server - Report MCP 微服务化版本

使用 FastAPI 将 Report MCP 暴露为独立 HTTP 服务，支持：
1. K8s 部署
2. 水平扩展
3. 独立监控和告警
4. 报告生成和导出

启动方式：
```bash
uvicorn apps.mcp.report_server:app --host 0.0.0.0 --port 5002
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from core.tools.mcp.report_mcp_contracts import (
    ReportHealthcheckResponse,
    ReportRenderRequest,
    ReportRenderResponse,
)
from core.tools.mcp.report_mcp_server import ReportMCPServer


# ============================================================================
# 全局实例（懒加载）
# ============================================================================

_report_mcp_server: ReportMCPServer | None = None


def get_report_mcp_server() -> ReportMCPServer:
    """获取或创建 Report MCP Server 实例"""
    global _report_mcp_server
    if _report_mcp_server is None:
        _report_mcp_server = ReportMCPServer()
    return _report_mcp_server


# ============================================================================
# FastAPI 应用
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    server = get_report_mcp_server()
    yield
    # 关闭时清理资源（如果需要）


app = FastAPI(
    title="Report MCP Server",
    description="报告生成微服务 - 支持 JSON/Markdown 报告导出",
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
async def mcp_call(request: dict) -> dict:
    """
    MCP 标准调用接口

    支持两种调用方式：
    1. render_report：生成报告
    2. healthcheck：健康检查

    Args:
        request: MCP 请求，格式 {"method": "...", "params": {...}}

    Returns:
        MCP 响应

    Example:
        POST /mcp/v1/call
        {
            "method": "render_report",
            "params": {
                "export_id": "export_001",
                "run_id": "run_xxx",
                "export_type": "markdown",
                "summary": "分析摘要",
                "insight_cards": [...],
                "report_blocks": [...],
                "tables": [...],
                "chart_spec": {...}
            }
        }
    """
    server = get_report_mcp_server()

    method = request.get("method")
    params = request.get("params", {})

    if method == "render_report":
        report_request = ReportRenderRequest(**params)
        response = server.render_report(report_request)
        return {
            "success": True,
            "result": {
                "export_id": response.export_id,
                "run_id": response.run_id,
                "export_type": response.export_type,
                "export_template": response.export_template,
                "filename": response.filename,
                "artifact_path": response.artifact_path,
                "file_uri": response.file_uri,
                "content_preview": response.content_preview,
                "metadata": response.metadata,
            },
        }
    elif method == "healthcheck":
        response = server.healthcheck()
        return {
            "success": True,
            "result": {
                "healthy": response.healthy,
                "server_mode": response.server_mode,
                "metadata": response.metadata,
            },
        }
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown method: {method}",
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
                "name": "render_report",
                "description": "生成并导出报告",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "export_id": {
                            "type": "string",
                            "description": "导出任务 ID",
                        },
                        "run_id": {
                            "type": "string",
                            "description": "分析任务 ID",
                        },
                        "export_type": {
                            "type": "string",
                            "description": "导出类型：json/markdown/docx/pdf",
                            "enum": ["json", "markdown", "docx", "pdf"],
                        },
                        "export_template": {
                            "type": "string",
                            "description": "导出模板名称（可选）",
                        },
                        "summary": {
                            "type": "string",
                            "description": "分析摘要",
                        },
                        "insight_cards": {
                            "type": "array",
                            "description": "洞察卡片列表",
                        },
                        "report_blocks": {
                            "type": "array",
                            "description": "报告块列表",
                        },
                        "tables": {
                            "type": "array",
                            "description": "数据表列表",
                        },
                        "chart_spec": {
                            "type": "object",
                            "description": "图表规格",
                        },
                        "metadata": {
                            "type": "object",
                            "description": "额外元数据",
                        },
                    },
                    "required": ["export_id", "run_id", "export_type"],
                },
            },
            {
                "name": "healthcheck",
                "description": "健康检查",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ],
        "server_info": {
            "name": "report-mcp",
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
        "name": "report-mcp",
        "version": "1.0.0",
        "description": "报告生成微服务",
        "capabilities": ["render_report", "healthcheck"],
        "tools": ["render_report", "healthcheck"],
    }


@app.get("/mcp/v1/status")
async def get_status() -> dict:
    """
    获取服务状态

    Returns:
        服务状态
    """
    server = get_report_mcp_server()
    health_response = server.healthcheck()

    return {
        "server_name": "report-mcp",
        "status": "online" if health_response.healthy else "degraded",
        "current_requests": 0,
        "max_concurrency": 10,
        "uptime_seconds": 0,
        "last_heartbeat": None,
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
# 业务接口
# ============================================================================

@app.post("/api/v1/report")
async def render_report(request: ReportRenderRequest) -> ReportRenderResponse:
    """
    生成报告（业务接口）

    Args:
        request: 报告生成请求

    Returns:
        报告生成结果
    """
    server = get_report_mcp_server()
    return server.render_report(request)


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
        "apps.mcp.report_server:app",
        host="0.0.0.0",
        port=5002,
        reload=False,
    )
