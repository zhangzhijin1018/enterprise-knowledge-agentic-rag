"""SQL MCP Server API 入口。

当前文件的作用不是直接参与主业务路由，
而是把“经营分析 SQL 执行底座”暴露成一个独立 FastAPI app 入口：
- 当前可以在进程内调用；
- 也可以单独启动用于调试 request / response contract；
- 后续如果拆成独立服务或远端 transport，这里就是最自然的 server 入口。
"""

from __future__ import annotations

from fastapi import Body, FastAPI, HTTPException

from core.analytics.schema_registry import SchemaRegistry
from core.tools.mcp import SQLHealthcheckRequest, SQLReadQueryRequest
from core.tools.mcp.sql_mcp_server import SQLMCPServer


def create_sql_mcp_app() -> FastAPI:
    """创建最小 SQL MCP Server 应用。"""

    app = FastAPI(
        title="SQL MCP Server",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    server = SQLMCPServer(schema_registry=SchemaRegistry())

    @app.post("/sql/execute_readonly_query")
    def execute_readonly_query(payload: dict = Body(...)) -> dict:
        """执行只读 SQL 查询。"""

        try:
            request = SQLReadQueryRequest(**payload)
            response = server.execute_readonly_query(request)
            return {
                "ok": True,
                "data": response.__dict__,
            }
        except Exception as exc:  # pragma: no cover - API 层兜底保护
            error_detail = getattr(exc, "detail", {"message": str(exc)})
            raise HTTPException(status_code=400, detail=error_detail) from exc

    @app.post("/sql/healthcheck")
    def healthcheck(payload: dict = Body(default_factory=dict)) -> dict:
        """执行最小健康检查。"""

        try:
            request = SQLHealthcheckRequest(**payload)
            response = server.healthcheck(request)
            return {
                "ok": True,
                "data": response.__dict__,
            }
        except Exception as exc:  # pragma: no cover - API 层兜底保护
            error_detail = getattr(exc, "detail", {"message": str(exc)})
            raise HTTPException(status_code=400, detail=error_detail) from exc

    return app


app = create_sql_mcp_app()
